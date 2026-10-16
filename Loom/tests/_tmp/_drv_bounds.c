/* _drv_bounds.c — 独立 C 驱动: 直接链接 pipeline.dll 调用 scene_bounds
 * 编译: cl /nologo /utf-8 /O2 _drv_bounds.c pipeline.lib
 * 用途: 排除 ctypes/Python 干扰, 定位数值偏差在 C 侧还是绑定侧。 */
#include <stdio.h>

__declspec(dllimport) int loom_pipeline_scene_bounds(
    const double *view_4x4, const double *aabb_rows, long long n,
    double *out_mn, double *out_mx);

int main(void)
{
    double view[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 10,20,30,1};
    double rows[6]  = {0,0,0, 1,1,1};
    double mn[3], mx[3];
    int rc, i;

    printf("view row3 (translation) = [%g %g %g %g]\n",
           view[12], view[13], view[14], view[15]);
    rc = loom_pipeline_scene_bounds(view, rows, 1, mn, mx);
    printf("rc=%d  mn=[%g %g %g]  mx=[%g %g %g]\n",
           rc, mn[0], mn[1], mn[2], mx[0], mx[1], mx[2]);
    printf("期望 mn=[10 20 30] mx=[11 21 31]\n");

    /* 再来一个: 只有 x 平移 5 */
    for (i = 0; i < 16; ++i) view[i] = (i % 5 == 0) ? 1.0 : 0.0;
    view[12] = 5.0;
    rc = loom_pipeline_scene_bounds(view, rows, 1, mn, mx);
    printf("x+5: rc=%d mn=[%g %g %g] mx=[%g %g %g] (期望 mn=[5 0 0] mx=[6 1 1])\n",
           rc, mn[0], mn[1], mn[2], mx[0], mx[1], mx[2]);
    return 0;
}
