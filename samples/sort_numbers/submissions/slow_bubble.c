/* Correct output, but bubble sort is O(n^2): too slow for the required O(n log n). */
#include <stdio.h>
#include <stdlib.h>

static void bubble_sort(int *values, int count) {
    for (int pass = 0; pass < count - 1; pass++) {
        for (int i = 0; i < count - 1 - pass; i++) {
            if (values[i] > values[i + 1]) {
                int tmp = values[i];
                values[i] = values[i + 1];
                values[i + 1] = tmp;
            }
        }
    }
}

int main(void) {
    int count;
    if (scanf("%d", &count) != 1 || count < 1) {
        return 1;
    }
    int *values = malloc((size_t)count * sizeof *values);
    if (values == NULL) {
        return 1;
    }
    for (int i = 0; i < count; i++) {
        if (scanf("%d", &values[i]) != 1) {
            free(values);
            return 1;
        }
    }
    bubble_sort(values, count);
    for (int i = 0; i < count; i++) {
        printf(i == 0 ? "%d" : " %d", values[i]);
    }
    printf("\n");
    free(values);
    return 0;
}
