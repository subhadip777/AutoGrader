#include <stdio.h>
#include <stdlib.h>

/* Stores the result through a pointer that was never allocated. */
static void add_into(int *out, int a, int b) {
    *out = a + b;
}

int main(void) {
    int a, b;
    int *result = NULL;
    if (scanf("%d %d", &a, &b) != 2) {
        return 1;
    }
    add_into(result, a, b);
    printf("%d\n", *result);
    return 0;
}
