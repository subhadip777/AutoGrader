// Student B: the same merge sort as similar_a.c with renamed identifiers,
// different comments and different layout. Token similarity still sees it.
#include <stdlib.h>
#include <stdio.h>

static void combine(int *data, int *buffer, int left, int middle, int right)
{
    int p = left, q = middle, out = left;
    while (p < middle && q < right) {
        if (data[p] <= data[q]) { buffer[out++] = data[p++]; }
        else { buffer[out++] = data[q++]; }
    }
    while (p < middle) { buffer[out++] = data[p++]; }
    while (q < right) { buffer[out++] = data[q++]; }
    for (out = left; out < right; out++) { data[out] = buffer[out]; }
}

static void sort_range(int *data, int *buffer, int left, int right)
{
    if (right - left < 2) { return; }
    int middle = left + (right - left) / 2;
    sort_range(data, buffer, left, middle);
    sort_range(data, buffer, middle, right);
    combine(data, buffer, left, middle, right);
}

int main(void)
{
    int count;
    if (scanf("%d", &count) != 1 || count < 1) { return 1; }
    int *data = malloc((size_t)count * sizeof *data);
    int *buffer = malloc((size_t)count * sizeof *buffer);
    if (data == NULL || buffer == NULL) { return 1; }
    for (int idx = 0; idx < count; idx++) {
        if (scanf("%d", &data[idx]) != 1) { return 1; }
    }
    sort_range(data, buffer, 0, count);
    for (int idx = 0; idx < count; idx++) { printf(idx ? " %d" : "%d", data[idx]); }
    printf("\n");
    free(data);
    free(buffer);
    return 0;
}
