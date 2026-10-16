/* ============================================================================
 * loom_module_ref.c — 契约头编译验证参考实现 (v1.0, 2026-09-08)
 * ============================================================================
 * 三个用途:
 *   1. 证明 loom_module.h 是合法 MSVC C 头 (编译闸门)
 *   2. 新核心组件 DLL 的脚手架模板 — 照抄改名字即可起步
 *   3. M1 探针 (加载器/模糊测试) 的无害测试靶 — 提供真实但行为良好的
 *      导出函数, 用于验证基座加载链正向通路 (坏行为靶由 fuzz harness
 *      的专用坏 DLL 承担)
 * 编译: 见同目录 build_ref.bat (cl /O2 /LD /MD, 与 ckernels 同款)
 * ========================================================================== */
#include "loom_module.h"
#include <string.h>

/* ---- 静态模块信息 (进程生命期有效; 不返回栈指针) -------------------------- */
static const LOOM_MODULE_INFO g_info = {
    LOOM_MODULE_MAGIC,
    LOOM_ABI_VERSION_CURRENT,
    "module_ref",          /* 模块 id: 每个真实组件改这里 */
    "1.0.0",
    1,                     /* official: 参考实现=官方组件 */
    1,                     /* provides_count */
    0,                     /* depends_count: 参考实现无依赖 */
    0
};

static const char *g_provides[] = { "module_ref.echo" };

/* ---- 7 个必须导出的最小函数集 --------------------------------------------- */
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
    return LOOM_OK;        /* 参考实现无设备资源 */
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

/* ---- 示例热路径: echo 张量 (验证 LOOM_TENSOR 裸参数通路) -------------------
 * 语义: 把 src 的前 total 个 f64 逐位拷到 dst; 校验形状/dtype。
 * 这就是"核心组件=接收数据/处理/吐出数据"的最小形态。 */
__declspec(dllexport) int32_t module_ref_echo(const LOOM_TENSOR *src,
                                              LOOM_TENSOR *dst)
{
    int64_t total, i;
    const double *s;
    double *d;
    if (src == NULL || dst == NULL || src->data == NULL || dst->data == NULL)
        return LOOM_ERR_PARAM;
    if (src->dtype != LOOM_DTYPE_F64 || dst->dtype != LOOM_DTYPE_F64)
        return LOOM_ERR_PARAM;
    if (src->ndim < 1 || src->ndim > LOOM_TENSOR_MAX_DIM)
        return LOOM_ERR_PARAM;
    total = 1;
    for (i = 0; i < src->ndim; ++i) total *= src->shape[i];
    s = (const double *)src->data;
    d = (double *)dst->data;
    for (i = 0; i < total; ++i) d[i] = s[i];
    return LOOM_OK;
}
