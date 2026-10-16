/* _dbg_bounds.c — 独立调试: 直接调用 loom_pipeline_scene_bounds, 排除 ctypes 干扰 */
#include <stdio.h>
#include <string.h>

typedef int int32_t;

/* 复制 pipeline 的实现 (便于断点/打印) */
static int32_t dbg_bounds(const double *view, const double *rows, long long n,
                          double *omn, double *omx)
{
    long long i; int c; int first = 1;
    double mn0 = 0, mn1 = 0, mn2 = 0, mx0 = 0, mx1 = 0, mx2 = 0;
    for (i = 0; i < n; ++i) {
        const double *row = rows + i * 6;
        double ax = row[0], ay = row[1], az = row[2];
        double bx = row[3], by = row[4], bz = row[5];
        for (c = 0; c < 8; ++c) {
            double cx = (c & 1) ? bx : ax;
            double cy = (c & 2) ? by : ay;
            double cz = (c & 4) ? bz : az;
            double w0 = view[0] * cx + view[1] * cy + view[2] * cz + view[3];
            double w1 = view[4] * cx + view[5] * cy + view[6] * cz + view[7];
            double w2 = view[8] * cx + view[9] * cy + view[10] * cz + view[11];
            if (first) { mn0 = mx0 = w0; mn1 = mx1 = w1; mn2 = mx2 = w2; first = 0; }
            else {
                if (w0 < mn0) mn0 = w0; else if (w0 > mx0) mx0 = w0;
                if (w1 < mn1) mn1 = w1; else if (w1 > mx1) mx1 = w1;
                if (w2 < mn2) mn2 = w2; else if (w2 > mx2) mx2 = w2;
            }
        }
    }
    omn[0] = mn0; omn[1] = mn1; omn[2] = mn2;
    omx[0] = mx0; omx[1] = mx1; omx[2] = mx2;
    return 0;
}

int main(void)
{
    double view[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 10,20,30,1};
    double rows[6] = {0,0,0, 1,1,1};
    double mn[3], mx[3];
    int i;
    dbg_bounds(view, rows, 1, mn, mx);
    printf("dbg mn=[%g %g %g] mx=[%g %g %g]\n", mn[0], mn[1], mn[2], mx[0], mx[1], mx[2]);
    printf("view row3 = [%g %g %g %g]\n", view[12], view[13], view[14], view[15]);
    return 0;
}
