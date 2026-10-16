/* ============================================================================
 * ambiguous.c — M1-2 校6「歧义注入」专用靶 (2026-09-08)
 * ============================================================================
 * ★★ 用途限制 (与 badvector.c 同款) ★★
 *   只用于 tests\_tmp\module_registry_check.py 验证 校6 接口冲突规则:
 *   不同 module_id 的模块提供了与在役模块相同的接口 → 保官方弃歧义。
 *   绝不写进 registry.json / 绝不随引擎发行。
 *
 * 与 badvector.c 的差别: module_id = "ambiguous" (≠ 被冲突的槽位 id),
 *   provides = ["ckernels.aabbs"] (与官方 ckernels 同接口, 但槽位不同名)。
 *   行为完全无害 (init 返 OK, 无崩溃向量) — 本靶测的是组装期冲突消解,
 *   不是运行期自愈 (后者由 badvector 承担)。
 * 编译: build_ambiguous.bat → ambiguous.dll
 * ========================================================================== */
#include "loom_module.h"
#include <string.h>

static const LOOM_MODULE_INFO g_info = {
    LOOM_MODULE_MAGIC,
    LOOM_ABI_VERSION_CURRENT,
    "ambiguous",           /* 槽位名与 ckernels 不同 → 属"歧义注入"而非"顶替" */
    "1.0.0",
    0,                     /* official=0: 用户注入, 走 sha256 信任闸 */
    1,                     /* provides_count */
    0,
    0
};

static const char *g_provides[] = { "ckernels.aabbs" };   /* 与官方 ckernels 撞接口 */

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
    return strcmp(iface_name, "ckernels.aabbs") == 0 ? 1 : 0;
}
