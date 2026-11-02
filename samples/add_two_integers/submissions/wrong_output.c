#include <stdio.h>

/* Prints a label before the number, which the output format does not allow. */
static int add(int a, int b) {
    return a + b;
}

int main(void) {
    int a, b;
    if (scanf("%d %d", &a, &b) != 2) {
        return 1;
    }
    printf("Sum = %d\n", add(a, b));
    return 0;
}
