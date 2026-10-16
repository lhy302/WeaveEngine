/* ============================================================================
 * loom_script.h — Loom 引擎 M4 脚本与运动组件 C ABI 契约 (v1.1, 2026-10-02)
 * ============================================================================
 * 职责:
 *   1. 承接 M4 极简运动类脚本 (自转/平移/速度阻尼等) 的纯 C 批处理
 *   2. 脱离 Python GIL 束缚, 达成 1000+ 物体纯 C 原生更新 <0.01ms
 *   3. 内嵌 Lua 5.4 静态虚拟机与安全沙箱, 承接纯 Lua 运动与玩家脚本执行
 * ========================================================================== */
#ifndef LOOM_SCRIPT_H
#define LOOM_SCRIPT_H

#include "../loom_module.h"

#ifdef _WIN32
#  define LOOM_SCRIPT_API __declspec(dllexport)
#else
#  define LOOM_SCRIPT_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* ---- ① 批量自转 (Batch Rotate) --------------------------------------------
 * 逐位对齐 RotateScript.update 的数学语义:
 *   out_rot = rot + radians(speeds) * dt
 * 输入:
 *   rot       : (n, 3) double 欧拉角弧度 [rx, ry, rz]
 *   speeds_deg: (n, 3) double 角速度(度/秒) [sx, sy, sz]
 *   dt        : double 逻辑步时间 (秒)
 *   n         : 物体总数
 * 输出:
 *   out_rot   : (n, 3) double 更新后的欧拉角弧度
 * 返回: LOOM_OK (0) / LOOM_ERR_PARAM (-2)
 */
LOOM_SCRIPT_API int32_t loom_script_batch_rotate(
    const double *rot,
    const double *speeds_deg,
    double dt,
    int64_t n,
    double *out_rot);

/* ---- ② 批量线性平移 (Batch Move) -------------------------------------------
 * 逐位对齐 LinearMove 的数学语义:
 *   out_pos = pos + velocity * dt
 * 输入:
 *   pos       : (n, 3) double 位置 [x, y, z]
 *   vel       : (n, 3) double 速度向量 [vx, vy, vz]
 *   dt        : double 逻辑步时间 (秒)
 *   n         : 物体总数
 * 输出:
 *   out_pos   : (n, 3) double 更新后的位置
 * 返回: LOOM_OK (0) / LOOM_ERR_PARAM (-2)
 */
LOOM_SCRIPT_API int32_t loom_script_batch_move(
    const double *pos,
    const double *vel,
    double dt,
    int64_t n,
    double *out_pos);

/* ---- ③ 嵌入式 Lua 5.4 虚拟机运行时与安全沙箱 ------------------------------
 * 提供轻量独立的 Lua 5.4 虚拟机实例, 无 Python GIL, 毫秒级创建与极低内存.
 */

typedef struct LoomLuaVM LoomLuaVM;

/* 创建安全沙箱化的 Lua 5.4 虚拟机实例 */
LOOM_SCRIPT_API LoomLuaVM *loom_script_lua_new(void);

/* 销毁虚拟机实例并释放内存 */
LOOM_SCRIPT_API void loom_script_lua_free(LoomLuaVM *vm);

/* 执行 Lua 脚本源码 (字符串) */
LOOM_SCRIPT_API int32_t loom_script_lua_dostring(LoomLuaVM *vm, const char *code);

/* 绑定当前操作物体的位姿内存与名称 (供 Lua 脚本直接操作)
 * pos: 指向 double[3] (x, y, z)
 * rot: 指向 double[3] (rx, ry, rz 弧度)
 */
LOOM_SCRIPT_API int32_t loom_script_lua_bind_entity(
    LoomLuaVM *vm,
    double *pos,
    double *rot,
    const char *name);

/* 注入按键状态 (供 Lua loom.is_key 查询) */
LOOM_SCRIPT_API int32_t loom_script_lua_set_key(
    LoomLuaVM *vm,
    const char *key,
    int32_t pressed);

/* 注入动作状态 (供 Lua loom.get_action 查询) */
LOOM_SCRIPT_API int32_t loom_script_lua_set_action(
    LoomLuaVM *vm,
    const char *action,
    int32_t active);

/* 注入相机目标指针 (供 Lua loom.set_camera_target / get_camera_target) */
LOOM_SCRIPT_API int32_t loom_script_lua_bind_camera(
    LoomLuaVM *vm,
    double *cam_target);

/* 触发 Lua 全局 on_start() 回调 */
LOOM_SCRIPT_API int32_t loom_script_lua_call_start(LoomLuaVM *vm);

/* 触发 Lua 全局 update(dt) 回调 */
LOOM_SCRIPT_API int32_t loom_script_lua_call_update(LoomLuaVM *vm, double dt);

/* 获取最近的 Lua 错误信息 (若有) */
LOOM_SCRIPT_API const char *loom_script_lua_get_error(LoomLuaVM *vm);

#ifdef __cplusplus
}
#endif

#endif /* LOOM_SCRIPT_H */
