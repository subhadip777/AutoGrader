#include <stdio.h>
#include <stdlib.h>

/* Prints the right answer, but writes one element past a 2-int buffer
 * and never frees it: ASan reports a heap-buffer-overflow. */
static int add(const int *values) {
    return values[0] + values[1];
}

int main(void) {
    int *values = malloc(2 * sizeof *values);
    if (values == NULL || scanf("%d %d", &values[0], &values[1]) != 2) {
        return 1;
    }
    values[2] = add(values);
    printf("%d\n", values[2]);
    return 0;
}
