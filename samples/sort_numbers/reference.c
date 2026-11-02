/* Instructor reference solution: qsort with an overflow-free comparison. */
#include <stdio.h>
#include <stdlib.h>

static int cmp(const void *x, const void *y) {
    long long a = *(const long long *)x, b = *(const long long *)y;
    return (a > b) - (a < b);
}

int main(void) {
    int n;
    if (scanf("%d", &n) != 1 || n < 0) {
        return 1;
    }
    long long *v = malloc((size_t)(n > 0 ? n : 1) * sizeof *v);
    if (v == NULL) {
        return 1;
    }
    for (int i = 0; i < n; i++) {
        if (scanf("%lld", &v[i]) != 1) {
            free(v);
            return 1;
        }
    }
    qsort(v, (size_t)n, sizeof *v, cmp);
    for (int i = 0; i < n; i++) {
        printf(i ? " %lld" : "%lld", v[i]);
    }
    printf("\n");
    free(v);
    return 0;
}
