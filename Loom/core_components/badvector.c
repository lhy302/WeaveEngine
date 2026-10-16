/* ============================================================================
 * badvector.c — M1-5 模糊测试专用坏靶 (访问违例向量), 2026-09-08
 * ============================================================================
 * ★★ 用途限制 (不可协商) ★★ 唯一用途: tests\_tmp\module_fuzz_check.py 的崩溃
 * 向量 (0xC0000005), 验证「ctypes OSError → crash_reporter.write_dump →
 * pop_and_fallback 弹出坏模块 → 官方顶回」自愈链。绝不写进 registry.json (任何
 * 形态, 含 enabled=false 条目); 绝不随引擎发行 (release/打包/同步脚本必须排除);
 * 除模糊测试探针外任何生产路径都不得加载 badvector.dll。脚手架: 照抄
 * loom_module_ref.c, 只改三处 — official=0 (用户注入, 走信任闸) / module_id
 * 顶替官方槽位 / echo 内故意空指针写入。契约 7 导出与签名与 ref 一致。
 * 编译: 见同目录 build_badvector.bat → badvector.dll (cl /O2 /LD /MD)
 * ========================================================================== */
#include "loom_module.h"
#include <string.h>

/* ---- 静态模块信息 (进程生命期有效; 不返回栈指针) -------------------------- */
static const LOOM_MODULE_INFO g_info = {
    LOOM_MODULE_MAGIC,
    LOOM_ABI_VERSION_CURRENT,
    "module_ref",          /* 顶替官方槽位: 同 module_id 换人 */
    "1.0.0",
    0,                     /* official=0: 用户注入, 走 sha256 信任闸 */
    1,                     /* provides_count */
    0,                     /* depends_count */
    0
};
static const char *g_provides[] = { "module_ref.echo" };

/* ---- 7 个必须导出的最小函数集 (与 ref 逐字节同款) ------------------------- */
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
    return NULL;           /* depends_count = 0 */
}

__declspec(dllexport) int32_t loom_module_init(void)
{
    return LOOM_OK;        /* 坏靶无设备资源: 组装期必须能通过 */
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
    return strcmp(iface_name, "module_ref.echo") == 0 ? 1 : 0;
}

/* ---- 崩溃向量热路径: echo 张量 → 空指针写入 (0xC0000005) -------------------
 * 签名与 ref 的 module_ref_echo 完全一致 (便于基座无差别顶替), 但函数体
 * 一进入就空指针写入。volatile 指针防编译器把 `*p = 1` 折叠掉 (否则 /O2
 * 下整段可能被优化为 UB 空转, 反而不崩)。 */
__declspec(dllexport) int32_t module_ref_echo(const LOOM_TENSOR *src,
                                              LOOM_TENSOR *dst)
{
    volatile int *p = NULL;
    (void)src;
    (void)dst;
    *p = 1;                /* 访问违例: ctypes 侧应捕获为 OSError */
    return LOOM_OK;        /* 不可达 */
}
