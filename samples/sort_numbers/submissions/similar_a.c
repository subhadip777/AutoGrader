/* Merge sort, written by student A. */
#include <stdio.h>
#include <stdlib.h>

static void merge(int *arr, int *tmp, int lo, int mid, int hi) {
    int i = lo, j = mid, k = lo;
    while (i < mid && j < hi) {
        if (arr[i] <= arr[j]) {
            tmp[k++] = arr[i++];
        } else {
            tmp[k++] = arr[j++];
        }
    }
    while (i < mid) {
        tmp[k++] = arr[i++];
    }
    while (j < hi) {
        tmp[k++] = arr[j++];
    }
    for (k = lo; k < hi; k++) {
        arr[k] = tmp[k];
    }
}

static void merge_sort(int *arr, int *tmp, int lo, int hi) {
    if (hi - lo < 2) {
        return;
    }
    int mid = lo + (hi - lo) / 2;
    merge_sort(arr, tmp, lo, mid);
    merge_sort(arr, tmp, mid, hi);
    merge(arr, tmp, lo, mid, hi);
}

int main(void) {
    int n;
    if (scanf("%d", &n) != 1 || n < 1) {
        return 1;
    }
    int *arr = malloc((size_t)n * sizeof *arr);
    int *tmp = malloc((size_t)n * sizeof *tmp);
    if (arr == NULL || tmp == NULL) {
        return 1;
    }
    for (int i = 0; i < n; i++) {
        if (scanf("%d", &arr[i]) != 1) {
            return 1;
        }
    }
    merge_sort(arr, tmp, 0, n);
    for (int i = 0; i < n; i++) {
        printf(i ? " %d" : "%d", arr[i]);
    }
    printf("\n");
    free(arr);
    free(tmp);
    return 0;
}
