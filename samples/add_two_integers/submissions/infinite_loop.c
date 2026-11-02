#include <stdio.h>

int main(void) {
    int a, b, sum = 0;
    if (scanf("%d %d", &a, &b) != 2) {
        return 1;
    }
    /* Bug: counts up to b, but i never changes, so the loop never ends. */
    for (int i = 0; i < b || b <= 0; ) {
        sum += 1;
    }
    printf("%d\n", a + sum);
    return 0;
}
