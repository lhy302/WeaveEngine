/* ============================================================================
 * loom_script.c — Loom 引擎 M4 脚本与运动组件 C 原生实现 (v1.1, 2026-10-02)
 * ============================================================================
 * 组件: script.dll (module_id="script", official=1)
 * 契约: ../loom_module.h + loom_script.h
 * ========================================================================== */

// @jev-block:imports:begin
#include "../loom_module.h"
#include "loom_script.h"
#include <string.h>
#include <stdlib.h>
#include <math.h>

#include "lua_src/lua.h"
#include "lua_src/lauxlib.h"
#include "lua_src/lualib.h"
// @jev-block:imports:end

#define LOOM_PI 3.14159265358979323846
#define LOOM_DEG2RAD (LOOM_PI / 180.0)

// @jev-block:batch_rotate:begin
LOOM_SCRIPT_API int32_t loom_script_batch_rotate(
    const double *rot,
    const double *speeds_deg,
    double dt,
    int64_t n,
    double *out_rot)
{
    int64_t i;
    if (rot == NULL || speeds_deg == NULL || out_rot == NULL)
        return LOOM_ERR_PARAM;
    if (n < 0) return LOOM_ERR_PARAM;
    if (n == 0) return LOOM_OK;

    for (i = 0; i < n; ++i) {
        size_t idx0 = (size_t)i * 3;
        size_t idx1 = idx0 + 1;
        size_t idx2 = idx0 + 2;

        out_rot[idx0] = rot[idx0] + (speeds_deg[idx0] * LOOM_DEG2RAD) * dt;
        out_rot[idx1] = rot[idx1] + (speeds_deg[idx1] * LOOM_DEG2RAD) * dt;
        out_rot[idx2] = rot[idx2] + (speeds_deg[idx2] * LOOM_DEG2RAD) * dt;
    }
    return LOOM_OK;
}
// @jev-block:batch_rotate:end

// @jev-block:batch_move:begin
LOOM_SCRIPT_API int32_t loom_script_batch_move(
    const double *pos,
    const double *vel,
    double dt,
    int64_t n,
    double *out_pos)
{
    int64_t i;
    if (pos == NULL || vel == NULL || out_pos == NULL)
        return LOOM_ERR_PARAM;
    if (n < 0) return LOOM_ERR_PARAM;
    if (n == 0) return LOOM_OK;

    for (i = 0; i < n; ++i) {
        size_t idx0 = (size_t)i * 3;
        size_t idx1 = idx0 + 1;
        size_t idx2 = idx0 + 2;

        out_pos[idx0] = pos[idx0] + vel[idx0] * dt;
        out_pos[idx1] = pos[idx1] + vel[idx1] * dt;
        out_pos[idx2] = pos[idx2] + vel[idx2] * dt;
    }
    return LOOM_OK;
}
// @jev-block:batch_move:end

// @jev-block:lua_vm:begin
struct LoomLuaVM {
    lua_State *L;
    double *curr_pos;
    double *curr_rot;
    double *cam_target;
    char entity_name[128];
    char last_error[512];
};

static LoomLuaVM *get_vm(lua_State *L)
{
    LoomLuaVM *vm = NULL;
    lua_pushstring(L, "__loom_vm");
    lua_rawget(L, LUA_REGISTRYINDEX);
    if (lua_islightuserdata(L, -1)) {
        vm = (LoomLuaVM *)lua_touserdata(L, -1);
    }
    lua_pop(L, 1);
    return vm;
}

static int l_loom_move(lua_State *L)
{
    LoomLuaVM *vm = get_vm(L);
    if (vm != NULL && vm->curr_pos != NULL) {
        double dx = luaL_checknumber(L, 1);
        double dy = luaL_checknumber(L, 2);
        double dz = luaL_checknumber(L, 3);
        vm->curr_pos[0] += dx;
        vm->curr_pos[1] += dy;
        vm->curr_pos[2] += dz;
    }
    return 0;
}

static int l_loom_rotate(lua_State *L)
{
    LoomLuaVM *vm = get_vm(L);
    if (vm != NULL && vm->curr_rot != NULL) {
        double rx = luaL_checknumber(L, 1);
        double ry = luaL_checknumber(L, 2);
        double rz = luaL_checknumber(L, 3);
        vm->curr_rot[0] += rx * LOOM_DEG2RAD;
        vm->curr_rot[1] += ry * LOOM_DEG2RAD;
        vm->curr_rot[2] += rz * LOOM_DEG2RAD;
    }
    return 0;
}

static int l_loom_get_position(lua_State *L)
{
    LoomLuaVM *vm = get_vm(L);
    if (vm != NULL && vm->curr_pos != NULL) {
        lua_pushnumber(L, vm->curr_pos[0]);
        lua_pushnumber(L, vm->curr_pos[1]);
        lua_pushnumber(L, vm->curr_pos[2]);
        return 3;
    }
    lua_pushnumber(L, 0.0);
    lua_pushnumber(L, 0.0);
    lua_pushnumber(L, 0.0);
    return 3;
}

static int l_loom_set_position(lua_State *L)
{
    LoomLuaVM *vm = get_vm(L);
    if (vm != NULL && vm->curr_pos != NULL) {
        vm->curr_pos[0] = luaL_checknumber(L, 1);
        vm->curr_pos[1] = luaL_checknumber(L, 2);
        vm->curr_pos[2] = luaL_checknumber(L, 3);
    }
    return 0;
}

static int l_loom_get_rotation(lua_State *L)
{
    LoomLuaVM *vm = get_vm(L);
    if (vm != NULL && vm->curr_rot != NULL) {
        lua_pushnumber(L, vm->curr_rot[0]);
        lua_pushnumber(L, vm->curr_rot[1]);
        lua_pushnumber(L, vm->curr_rot[2]);
        return 3;
    }
    lua_pushnumber(L, 0.0);
    lua_pushnumber(L, 0.0);
    lua_pushnumber(L, 0.0);
    return 3;
}

static int l_loom_set_rotation(lua_State *L)
{
    LoomLuaVM *vm = get_vm(L);
    if (vm != NULL && vm->curr_rot != NULL) {
        vm->curr_rot[0] = luaL_checknumber(L, 1);
        vm->curr_rot[1] = luaL_checknumber(L, 2);
        vm->curr_rot[2] = luaL_checknumber(L, 3);
    }
    return 0;
}

static int l_loom_is_key(lua_State *L)
{
    const char *key = luaL_checkstring(L, 1);
    lua_pushstring(L, "__loom_keys");
    lua_rawget(L, LUA_REGISTRYINDEX);
    if (lua_istable(L, -1)) {
        lua_pushstring(L, key);
        lua_rawget(L, -2);
        int pressed = lua_toboolean(L, -1);
        lua_pop(L, 2);
        lua_pushboolean(L, pressed);
        return 1;
    }
    lua_pop(L, 1);
    lua_pushboolean(L, 0);
    return 1;
}

static int l_loom_get_action(lua_State *L)
{
    const char *act = luaL_checkstring(L, 1);
    lua_pushstring(L, "__loom_actions");
    lua_rawget(L, LUA_REGISTRYINDEX);
    if (lua_istable(L, -1)) {
        lua_pushstring(L, act);
        lua_rawget(L, -2);
        int active = lua_toboolean(L, -1);
        lua_pop(L, 2);
        lua_pushboolean(L, active);
        return 1;
    }
    lua_pop(L, 1);
    lua_pushboolean(L, 0);
    return 1;
}

static int l_loom_set_camera_target(lua_State *L)
{
    LoomLuaVM *vm = get_vm(L);
    if (vm != NULL && vm->cam_target != NULL) {
        vm->cam_target[0] = luaL_checknumber(L, 1);
        vm->cam_target[1] = luaL_checknumber(L, 2);
        vm->cam_target[2] = luaL_checknumber(L, 3);
    }
    return 0;
}

static int l_loom_get_camera_target(lua_State *L)
{
    LoomLuaVM *vm = get_vm(L);
    if (vm != NULL && vm->cam_target != NULL) {
        lua_pushnumber(L, vm->cam_target[0]);
        lua_pushnumber(L, vm->cam_target[1]);
        lua_pushnumber(L, vm->cam_target[2]);
        return 3;
    }
    lua_pushnumber(L, 0.0);
    lua_pushnumber(L, 0.0);
    lua_pushnumber(L, 0.0);
    return 3;
}

static int l_loom_get_name(lua_State *L)
{
    LoomLuaVM *vm = get_vm(L);
    if (vm != NULL) {
        lua_pushstring(L, vm->entity_name);
    } else {
        lua_pushstring(L, "");
    }
    return 1;
}

LOOM_SCRIPT_API LoomLuaVM *loom_script_lua_new(void)
{
    LoomLuaVM *vm = (LoomLuaVM *)malloc(sizeof(LoomLuaVM));
    if (vm == NULL) return NULL;
    memset(vm, 0, sizeof(LoomLuaVM));

    lua_State *L = luaL_newstate();
    if (L == NULL) {
        free(vm);
        return NULL;
    }
    vm->L = L;

    /* 开启安全基础标准库 (math, string, table, utf8) */
    luaL_requiref(L, "_G", luaopen_base, 1);
    lua_pop(L, 1);
    luaL_requiref(L, "math", luaopen_math, 1);
    lua_pop(L, 1);
    luaL_requiref(L, "string", luaopen_string, 1);
    lua_pop(L, 1);
    luaL_requiref(L, "table", luaopen_table, 1);
    lua_pop(L, 1);
    luaL_requiref(L, "utf8", luaopen_utf8, 1);
    lua_pop(L, 1);

    /* 沙箱加固: 剥离可能突破文件系统的危险内置函数 */
    lua_pushnil(L); lua_setglobal(L, "dofile");
    lua_pushnil(L); lua_setglobal(L, "loadfile");

    /* 注册表存 vm 指针 */
    lua_pushstring(L, "__loom_vm");
    lua_pushlightuserdata(L, vm);
    lua_rawset(L, LUA_REGISTRYINDEX);

    /* 注册表存 keys 与 actions 散列表 */
    lua_pushstring(L, "__loom_keys");
    lua_newtable(L);
    lua_rawset(L, LUA_REGISTRYINDEX);

    lua_pushstring(L, "__loom_actions");
    lua_newtable(L);
    lua_rawset(L, LUA_REGISTRYINDEX);

    /* 暴露全局 loom 模块 */
    lua_newtable(L);
    lua_pushcfunction(L, l_loom_move); lua_setfield(L, -2, "move");
    lua_pushcfunction(L, l_loom_rotate); lua_setfield(L, -2, "rotate");
    lua_pushcfunction(L, l_loom_get_position); lua_setfield(L, -2, "get_position");
    lua_pushcfunction(L, l_loom_set_position); lua_setfield(L, -2, "set_position");
    lua_pushcfunction(L, l_loom_get_rotation); lua_setfield(L, -2, "get_rotation");
    lua_pushcfunction(L, l_loom_set_rotation); lua_setfield(L, -2, "set_rotation");
    lua_pushcfunction(L, l_loom_is_key); lua_setfield(L, -2, "is_key");
    lua_pushcfunction(L, l_loom_get_action); lua_setfield(L, -2, "get_action");
    lua_pushcfunction(L, l_loom_set_camera_target); lua_setfield(L, -2, "set_camera_target");
    lua_pushcfunction(L, l_loom_get_camera_target); lua_setfield(L, -2, "get_camera_target");
    lua_pushcfunction(L, l_loom_get_name); lua_setfield(L, -2, "get_name");
    lua_setglobal(L, "loom");

    return vm;
}

LOOM_SCRIPT_API void loom_script_lua_free(LoomLuaVM *vm)
{
    if (vm == NULL) return;
    if (vm->L != NULL) {
        lua_close(vm->L);
        vm->L = NULL;
    }
    free(vm);
}

LOOM_SCRIPT_API int32_t loom_script_lua_dostring(LoomLuaVM *vm, const char *code)
{
    if (vm == NULL || vm->L == NULL || code == NULL) return LOOM_ERR_PARAM;
    int rc = luaL_dostring(vm->L, code);
    if (rc != LUA_OK) {
        const char *err = lua_tostring(vm->L, -1);
        if (err) strncpy_s(vm->last_error, sizeof(vm->last_error), err, sizeof(vm->last_error) - 1);
        lua_pop(vm->L, 1);
        return -1;
    }
    return LOOM_OK;
}

LOOM_SCRIPT_API int32_t loom_script_lua_bind_entity(
    LoomLuaVM *vm,
    double *pos,
    double *rot,
    const char *name)
{
    if (vm == NULL) return LOOM_ERR_PARAM;
    vm->curr_pos = pos;
    vm->curr_rot = rot;
    if (name) {
        strncpy_s(vm->entity_name, sizeof(vm->entity_name), name, sizeof(vm->entity_name) - 1);
    } else {
        vm->entity_name[0] = '\0';
    }
    return LOOM_OK;
}

LOOM_SCRIPT_API int32_t loom_script_lua_set_key(
    LoomLuaVM *vm,
    const char *key,
    int32_t pressed)
{
    if (vm == NULL || vm->L == NULL || key == NULL) return LOOM_ERR_PARAM;
    lua_pushstring(vm->L, "__loom_keys");
    lua_rawget(vm->L, LUA_REGISTRYINDEX);
    if (lua_istable(vm->L, -1)) {
        lua_pushstring(vm->L, key);
        lua_pushboolean(vm->L, pressed != 0);
        lua_rawset(vm->L, -3);
    }
    lua_pop(vm->L, 1);
    return LOOM_OK;
}

LOOM_SCRIPT_API int32_t loom_script_lua_set_action(
    LoomLuaVM *vm,
    const char *action,
    int32_t active)
{
    if (vm == NULL || vm->L == NULL || action == NULL) return LOOM_ERR_PARAM;
    lua_pushstring(vm->L, "__loom_actions");
    lua_rawget(vm->L, LUA_REGISTRYINDEX);
    if (lua_istable(vm->L, -1)) {
        lua_pushstring(vm->L, action);
        lua_pushboolean(vm->L, active != 0);
        lua_rawset(vm->L, -3);
    }
    lua_pop(vm->L, 1);
    return LOOM_OK;
}

LOOM_SCRIPT_API int32_t loom_script_lua_bind_camera(
    LoomLuaVM *vm,
    double *cam_target)
{
    if (vm == NULL) return LOOM_ERR_PARAM;
    vm->cam_target = cam_target;
    return LOOM_OK;
}

LOOM_SCRIPT_API int32_t loom_script_lua_call_start(LoomLuaVM *vm)
{
    if (vm == NULL || vm->L == NULL) return LOOM_ERR_PARAM;
    lua_getglobal(vm->L, "on_start");
    if (!lua_isfunction(vm->L, -1)) {
        lua_pop(vm->L, 1);
        return LOOM_OK;
    }
    int rc = lua_pcall(vm->L, 0, 0, 0);
    if (rc != LUA_OK) {
        const char *err = lua_tostring(vm->L, -1);
        if (err) strncpy_s(vm->last_error, sizeof(vm->last_error), err, sizeof(vm->last_error) - 1);
        lua_pop(vm->L, 1);
        return -1;
    }
    return LOOM_OK;
}

LOOM_SCRIPT_API int32_t loom_script_lua_call_update(LoomLuaVM *vm, double dt)
{
    if (vm == NULL || vm->L == NULL) return LOOM_ERR_PARAM;
    lua_getglobal(vm->L, "update");
    if (!lua_isfunction(vm->L, -1)) {
        lua_pop(vm->L, 1);
        return LOOM_OK;
    }
    lua_pushnumber(vm->L, dt);
    int rc = lua_pcall(vm->L, 1, 0, 0);
    if (rc != LUA_OK) {
        const char *err = lua_tostring(vm->L, -1);
        if (err) strncpy_s(vm->last_error, sizeof(vm->last_error), err, sizeof(vm->last_error) - 1);
        lua_pop(vm->L, 1);
        return -1;
    }
    return LOOM_OK;
}

LOOM_SCRIPT_API const char *loom_script_lua_get_error(LoomLuaVM *vm)
{
    if (vm == NULL) return "";
    return vm->last_error;
}
// @jev-block:lua_vm:end

/* ============================================================================
 * 契约导出 (loom_module.h v1.0 最小函数集 7 个)
 * ========================================================================== */
static const LOOM_MODULE_INFO g_info = {
    LOOM_MODULE_MAGIC,
    LOOM_ABI_VERSION_CURRENT,
    "script",              /* 模块 id */
    "1.0.0",
    1,                     /* official=1: 官方组件 */
    2,                     /* provides_count */
    0,                     /* depends_count */
    0
};

static const char *g_provides[] = {
    "script.batch_rotate",
    "script.batch_move"
};

__declspec(dllexport) const LOOM_MODULE_INFO *loom_module_info(void)
{
    return &g_info;
}

__declspec(dllexport) const char *loom_module_provide(uint32_t index)
{
    if (index >= g_info.provides_count) return NULL;
    return g_provides[index];
}

__declspec(dllexport) const char *loom_module_depend(uint32_t index)
{
    (void)index;
    return NULL;
}

__declspec(dllexport) int32_t loom_module_init(void)
{
    return LOOM_OK;
}

__declspec(dllexport) void loom_module_deinit(void)
{
}

__declspec(dllexport) uint32_t loom_module_abi(void)
{
    return LOOM_ABI_VERSION_CURRENT;
}

__declspec(dllexport) int32_t loom_module_has(const char *iface_name)
{
    if (iface_name == NULL) return 0;
    if (strcmp(iface_name, "script.batch_rotate") == 0) return 1;
    if (strcmp(iface_name, "script.batch_move") == 0) return 1;
    if (strcmp(iface_name, "script.lua_vm") == 0) return 1;
    return 0;
}
