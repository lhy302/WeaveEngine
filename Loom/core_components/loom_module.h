/* ============================================================================
 * loom_module.h — Loom 引擎 DLL 化统一 C ABI 契约 (v1.0, 2026-09-08)
 * ============================================================================
 * 战役总纲: D:\my-project\DLL化改造可行性方案与执行路径报告.txt (v1.3) §3.1
 * 地位: 所有核心组件 DLL 与 Python 基座之间唯一耦合点。ABI 一旦冻结改动
 *       代价大, 设计从保守 (版本号给足余量 / 字段留 reserved)。
 *
 * 风格对齐: 与 ckernels\loom_kernels.c 成熟惯例同源 —
 *   纯 C (MSVC C89/C99 兼容, 无 C++ 特性) / extern "C" / POD 结构体 /
 *   int 返回错误码 (0=成功, 负数=错误) / 裸缓冲区 (指针+形状+dtype)。
 *
 * ★两条所有权铁律 (报告 §3.2):
 *   1. 帧内缓冲区 = 基座 arena 预分配 (grow-only), DLL 收 LOOM_TENSOR
 *      裸参数, 绝不在帧路径 malloc/free。
 *   2. DLL 私有资源 (物理世界/音频设备等设备类) 归 DLL 管, 生命周期由
 *      loom_module_init / loom_module_deinit 显式交接。
 *
 * ★热重载铁律 (报告 M1): DLL 无跨帧隐藏状态。跨帧状态 (物体位置/速度/
 *   场景图) 全部留基座; DLL 内只有 init 建立的设备资源。换 DLL 流程 =
 *   deinit → FreeLibrary → LoadLibrary(新) → init → 继续跑, 场景零迁移。
 * ========================================================================== */
#ifndef LOOM_MODULE_H
#define LOOM_MODULE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- 魔数与 ABI 版本 ------------------------------------------------------
 * 魔数: 内存字节序 = 'L','O','O','M' (uint32 小端值 0x4D4F4F4C)。
 * ABI 版本编码: 高 16 位 = 主版本 (破坏性变更, 拒绝加载),
 *               低 16 位 = 次版本 (向后兼容追加, 允许)。
 * 基座校验规则: 主版本必须相等; DLL 次版本 > 基座已知次版本 = 允许 (DLL 更新)
 *               且基座按已知接口调用; DLL 主版本不符 = 拒绝加载。 */
#define LOOM_MODULE_MAGIC 0x4D4F4F4Cu
#define LOOM_ABI_MAKE(major, minor) \
    ((((uint32_t)(major)) << 16) | (((uint32_t)(minor)) & 0xFFFFu))
#define LOOM_ABI_MAJOR(v)  ((v) >> 16)
#define LOOM_ABI_MINOR(v)  ((v) & 0xFFFFu)
#define LOOM_ABI_VERSION_CURRENT LOOM_ABI_MAKE(1, 0)

/* 接口名/模块 id 字符串上限 (不含终止符)。provides/depends 命名建议
 * "组件.接口" 点分式, 如 "pipeline.logic_step" / "pipeline.aabbs"。 */
#define LOOM_NAME_MAX 63

/* ---- 模块信息 (POD, 每个 DLL 必须能返回一份静态存储) --------------------- */
typedef struct LOOM_MODULE_INFO {
    uint32_t magic;        /* 必须 == LOOM_MODULE_MAGIC, 否则拒绝加载 */
    uint32_t abi_version;  /* 必须 == LOOM_ABI_VERSION_CURRENT 主版本 */
    char     module_id[LOOM_NAME_MAX + 1]; /* 模块唯一 id, 如 "pipeline" */
    char     version[16];  /* 模块自身语义版本 "1.0.0" (人读+注册表比对) */
    uint32_t official;     /* 1=官方组件 (随引擎发行) 0=用户注入 (走信任闸:
                              SHA256 校验+首次启用确认, 挂钩在基座加载器) */
    uint32_t provides_count; /* 本模块提供的接口数 (经 loom_module_provide 枚举) */
    uint32_t depends_count;  /* 本模块依赖的接口数 (经 loom_module_depend 枚举) */
    uint32_t reserved;     /* 置 0; 未来扩展 (如 flags: 可选能力位图) */
} LOOM_MODULE_INFO;

/* ---- 帧数据张量描述 (裸缓冲区参数的统一 POD 形态) -------------------------
 * 基座 arena 预分配, DLL 按描述读/写; 不用的维度填 1, ndim 之外的 shape 置 0。
 * 行主序 C 连续, 与 numpy ascontiguousarray 产出一致 (ckernels 同款约定)。 */
#define LOOM_TENSOR_MAX_DIM 4
typedef struct LOOM_TENSOR {
    void   *data;                     /* 基座 arena 缓冲区 (非 const 由用途定) */
    int64_t shape[LOOM_TENSOR_MAX_DIM];
    int32_t ndim;                     /* 实际维度 1..4 */
    int32_t dtype;                    /* LOOM_DTYPE_* */
} LOOM_TENSOR;

#define LOOM_DTYPE_F32 0
#define LOOM_DTYPE_F64 1
#define LOOM_DTYPE_I32 2
#define LOOM_DTYPE_I64 3
#define LOOM_DTYPE_U8  4

/* ---- 错误码公约 (int 返回: 0=成功, 负数=错误) -----------------------------
 * -1/-2 沿用 loom_kernels 现行惯例; 其余为本契约新增。 */
#define LOOM_OK             0    /* 成功 */
#define LOOM_ERR_CAPACITY  (-1)  /* 容量不足 (输出缓冲不够, 调用方扩 arena 重试) */
#define LOOM_ERR_PARAM     (-2)  /* 参数非法 (空指针/形状错误/dtype 不符) */
#define LOOM_ERR_INTERNAL  (-3)  /* DLL 内部错误 (状态可能不可信, 基座应考虑弹出) */
#define LOOM_ERR_ABI       (-4)  /* 接口不兼容 (版本/能力不符) */
#define LOOM_ERR_NO_INIT   (-5)  /* 资源未初始化 (init 未调或已 deinit) */
#define LOOM_ERR_UNSUPPORTED (-6)/* 能力未实现 (可选接口缺席) */

/* ============================================================================
 * 每个 DLL 必须导出的最小函数集 (7 个, 全部 extern "C"):
 * 基座加载流程: LoadLibrary → GetProcAddress 逐一验在 → 校验 magic/abi →
 *   读 provides/depends → 注册表依赖校验 → init → 投入使用。
 * 具体热路径签名 (如 pipeline 的帧步进) 由各组件在 M2+ 自己的头文件声明,
 * 本契约只定通用骨架与公约。
 * ========================================================================== */

/* 1) 模块信息: 返回静态存储指针 (进程生命期有效, DLL 不得返回栈指针) */
typedef const LOOM_MODULE_INFO *(*loom_module_info_fn)(void);

/* 2) 枚举 provides: index ∈ [0, provides_count), 越界返回 NULL */
typedef const char *(*loom_module_provide_fn)(uint32_t index);

/* 3) 枚举 depends: 同上 */
typedef const char *(*loom_module_depend_fn)(uint32_t index);

/* 4) 资源建立: 设备类资源 (物理世界/音频设备等) 在此建立。
 *    返回 LOOM_OK 或负错误码; 失败后基座可 FreeLibrary 弹出。
 *    ★可重入: 同一 DLL 被 deinit 后再 init 必须能干净重建。 */
typedef int32_t (*loom_module_init_fn)(void);

/* 5) 资源释放: 热重载前必调; 之后 DLL 内不得再持有任何基座指针 */
typedef void (*loom_module_deinit_fn)(void);

/* 6) ABI 版本快捷查询 (免解引用 info 的小便利, 建议导出) */
typedef uint32_t (*loom_module_abi_fn)(void);

/* 7) 可选接口枚举: 查询某命名接口是否存在/可用 (能力查询)。
 *    返回 1=可用, 0=不可用。可选导出; 缺席 = 基座按 0 处理。 */
typedef int32_t (*loom_module_has_fn)(const char *iface_name);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LOOM_MODULE_H */
