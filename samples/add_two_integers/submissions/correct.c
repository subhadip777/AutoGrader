/* Sum of two integers.
 * The values are read and added as long long, so even sums beyond the
 * range of int (for example INT_MAX + 1) are printed exactly. */
#include <stdio.h>

/* Returns lhs + rhs without overflow for any pair of 32-bit inputs. */
static long long add_values(long long lhs, long long rhs) {
    return lhs + rhs;
}

int main(void) {
    long long lhs, rhs;

    if (scanf("%lld %lld", &lhs, &rhs) != 2) {
        fprintf(stderr, "expected two integers\n");
        return 1;
    }
    printf("%lld\n", add_values(lhs, rhs));
    return 0;
}
