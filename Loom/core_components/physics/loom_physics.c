#include <stdio.h>
#include <stdbool.h>
/* ============================================================================
 * loom_physics.c — Loom 引擎 M4 物理动力学核心组件 C 原生实现 (v1.0, 2026-10-02)
 * ============================================================================
 * 组件: physics.dll (module_id="physics", official=1)
 * 契约: ../loom_module.h
 * ========================================================================== */

// @jev-block:imports:begin
#include "../loom_module.h"
#include <string.h>
#include <stdlib.h>
#include <math.h>
// @jev-block:imports:end

#ifdef _WIN32
#  define LOOM_PHYSICS_API __declspec(dllexport)
#else
#  define LOOM_PHYSICS_API
#endif

#define LOOM_PHYSICS_ROLLING_K 23.0
#define LOOM_PHYSICS_ROLLING_ANG_EPS 0.06
#define LOOM_PHYSICS_V_STALL_EPS 0.03
#define LOOM_PHYSICS_W_STALL_EPS 0.3
#define LOOM_PHYSICS_VY_STOP_GATE 1.0

// @jev-block:pre_step:begin
LOOM_PHYSICS_API int32_t loom_physics_pre_step(
    double *lin_vel,
    double *ang_vel,
    const uint8_t *is_dynamic,
    const uint8_t *use_gravity,
    const uint8_t *is_active,
    const double *friction,
    const double *rolling_fric,
    double gravity_y,
    double dt,
    int64_t n) /* start */
{ /* body */
    int64_t i;
    if (lin_vel == NULL || ang_vel == NULL || is_dynamic == NULL ||
        use_gravity == NULL || is_active == NULL || friction == NULL ||
        rolling_fric == NULL) /* check */
    { /* param */
        return LOOM_ERR_PARAM;
    } /* param */
    if (n < 0) return LOOM_ERR_PARAM;
    if (n == 0) return LOOM_OK;
    for (i = 0; i < n; ++i) /* loop */
    { /* for */
        size_t idx;
        if (!is_dynamic[i]) continue;
        idx = (size_t)i * 3;
        if (use_gravity[i] && is_active[i]) /* grav */
        { /* grav */
            lin_vel[idx + 1] += gravity_y * dt;
        } /* grav */
        if (is_active[i]) /* act */
        { /* act */
            double wx = ang_vel[idx];
            double wy = ang_vel[idx + 1];
            double wz = ang_vel[idx + 2];
            double ang_speed = sqrt(wx * wx + wy * wy + wz * wz);
            if (ang_speed > LOOM_PHYSICS_ROLLING_ANG_EPS) /* roll */
            { /* roll */
                double decay = 1.0 - friction[i] * rolling_fric[i] * LOOM_PHYSICS_ROLLING_K * dt;
                if (decay < 0.0) decay = 0.0;
                ang_vel[idx]     *= decay;
                ang_vel[idx + 1] *= decay;
                ang_vel[idx + 2] *= decay;
                lin_vel[idx]     *= decay;
                lin_vel[idx + 2] *= decay;
            } /* roll */
            double vx = lin_vel[idx];
            double vy = lin_vel[idx + 1];
            double vz = lin_vel[idx + 2];
            double vh = sqrt(vx * vx + vz * vz);
            if (vh < LOOM_PHYSICS_V_STALL_EPS &&
                ang_speed < LOOM_PHYSICS_W_STALL_EPS &&
                fabs(vy) < LOOM_PHYSICS_VY_STOP_GATE) /* stall */
            { /* stall */
                lin_vel[idx]     = 0.0;
                lin_vel[idx + 2] = 0.0;
                ang_vel[idx]     = 0.0;
                ang_vel[idx + 1] = 0.0;
                ang_vel[idx + 2] = 0.0;
            } /* stall */
        } /* act */
    } /* for */
    return LOOM_OK;
} /* body */
// @jev-block:pre_step:end
// @jev-block:post_step:begin
LOOM_PHYSICS_API int32_t loom_physics_post_step(
    double *lin_vel,
    double *ang_vel,
    const uint8_t *is_active,
    int64_t n) /* start */
{ /* body */
    int64_t i;
    if (lin_vel == NULL || ang_vel == NULL || is_active == NULL) /* check */
    { /* check */
        return LOOM_ERR_PARAM;
    } /* check */
    if (n < 0) return LOOM_ERR_PARAM;
    if (n == 0) return LOOM_OK;
    for (i = 0; i < n; ++i) /* loop */
    { /* for */
        if (!is_active[i]) /* sleep */
        { /* sleep */
            size_t idx = (size_t)i * 3;
            lin_vel[idx]     = 0.0;
            lin_vel[idx + 1] = 0.0;
            lin_vel[idx + 2] = 0.0;
            ang_vel[idx]     = 0.0;
            ang_vel[idx + 1] = 0.0;
            ang_vel[idx + 2] = 0.0;
        } /* sleep */
    } /* for */
    return LOOM_OK;
} /* body */
// @jev-block:post_step:end
// @jev-block:substep_loop:begin
typedef int32_t (*LoomPhysicsStepCallback)(double dt, void *user_ctx);
LOOM_PHYSICS_API int32_t loom_physics_substep_loop(
    double *lin_vel,
    double *ang_vel,
    const uint8_t *is_dynamic,
    const uint8_t *use_gravity,
    const uint8_t *is_active,
    const double *friction,
    const double *rolling_fric,
    double gravity_y,
    double sub_dt,
    int32_t num_substeps,
    int64_t n,
    LoomPhysicsStepCallback step_cb,
    void *user_ctx) /* start */
{ /* body */
    int32_t step_idx;
    if (num_substeps <= 0) return LOOM_OK;
    for (step_idx = 0; step_idx < num_substeps; ++step_idx) /* step_loop */
    { /* step_loop */
        int32_t rc = loom_physics_pre_step(
            lin_vel, ang_vel, is_dynamic, use_gravity, is_active,
            friction, rolling_fric, gravity_y, sub_dt, n);
        if (rc != LOOM_OK) return rc;
        if (step_cb != NULL) /* cb */
        { /* cb */
            rc = step_cb(sub_dt, user_ctx);
            if (rc != LOOM_OK) return rc;
        } /* cb */
        rc = loom_physics_post_step(lin_vel, ang_vel, is_active, n);
        if (rc != LOOM_OK) return rc;
    } /* step_loop */
    return LOOM_OK;
} /* body */
// @jev-block:substep_loop:end
// @jev-block:module_abi:begin
static const LOOM_MODULE_INFO g_physics_info = /* info */
{ /* info */
    LOOM_MODULE_MAGIC,
    LOOM_ABI_VERSION_CURRENT,
    "physics",
    "1.0.0",
    1,
    3,
    0,
    0
};

static const char *g_physics_provides[] = /* prov */
{ /* prov */
    "physics.pre_step",
    "physics.post_step",
    "physics.substep_loop"
};

LOOM_PHYSICS_API const LOOM_MODULE_INFO *loom_module_info(void) /* info_fn */
{ /* info_fn */
    return &g_physics_info;
} /* info_fn */

LOOM_PHYSICS_API const char *loom_module_provide(uint32_t index) /* prov_fn */
{ /* prov_fn */
    if (index >= g_physics_info.provides_count) return NULL;
    return g_physics_provides[index];
} /* prov_fn */

LOOM_PHYSICS_API const char *loom_module_depend(uint32_t index) /* dep_fn */
{ /* dep_fn */
    (void)index;
    return NULL;
} /* dep_fn */

LOOM_PHYSICS_API int32_t loom_module_init(void) /* init_fn */
{ /* init_fn */
    return LOOM_OK;
} /* init_fn */

LOOM_PHYSICS_API void loom_module_deinit(void) /* deinit_fn */
{ /* deinit_fn */
} /* deinit_fn */

LOOM_PHYSICS_API uint32_t loom_module_abi(void) /* abi_fn */
{ /* abi_fn */
    return LOOM_ABI_VERSION_CURRENT;
} /* abi_fn */

LOOM_PHYSICS_API int32_t loom_module_has(const char *iface_name) /* has_fn */
{ /* has_fn */
    if (iface_name == NULL) return 0;
    if (strcmp(iface_name, "physics.pre_step") == 0) return 1;
    if (strcmp(iface_name, "physics.post_step") == 0) return 1;
    if (strcmp(iface_name, "physics.substep_loop") == 0) return 1;
    return 0;
} /* has_fn */
// @jev-block:module_abi:end
