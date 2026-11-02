#include <stdio.h>

/* Correct output, but -Wall -Wextra reports an unused parameter,
 * an unused variable and a signed/unsigned comparison. */
static int add(int a, int b, int scale) {
    return a + b;
}

int main(void) {
    int a, b, spare;
    unsigned limit = 10;
    if (scanf("%d %d", &a, &b) != 2) {
        return 1;
    }
    if (a < limit) {
        a = a + 0;
    }
    printf("%d\n", add(a, b, 1));
    return 0;
}
