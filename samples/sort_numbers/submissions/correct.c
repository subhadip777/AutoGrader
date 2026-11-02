/* Sort n integers in O(n log n) with the C library's qsort. */
#include <stdio.h>
#include <stdlib.h>

/* Compares two ints without the overflow that "a - b" would cause. */
static int compare_ints(const void *left, const void *right) {
    int a = *(const int *)left;
    int b = *(const int *)right;
    return (a > b) - (a < b);
}

/* Reads count values into a new array; returns NULL on bad input. */
static int *read_values(int count) {
    int *values = malloc((size_t)count * sizeof *values);
    if (values == NULL) {
        return NULL;
    }
    for (int i = 0; i < count; i++) {
        if (scanf("%d", &values[i]) != 1) {
            free(values);
            return NULL;
        }
    }
    return values;
}

static void print_values(const int *values, int count) {
    for (int i = 0; i < count; i++) {
        printf(i == 0 ? "%d" : " %d", values[i]);
    }
    printf("\n");
}

int main(void) {
    int count;
    if (scanf("%d", &count) != 1 || count < 1) {
        return 1;
    }
    int *values = read_values(count);
    if (values == NULL) {
        return 1;
    }
    qsort(values, (size_t)count, sizeof *values, compare_ints);
    print_values(values, count);
    free(values);
    return 0;
}
