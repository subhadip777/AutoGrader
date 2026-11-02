from server import sandbox

MEM_HOG = r'''#include <stdio.h>
#include <stdlib.h>
int main(void) {
    size_t n = 400u * 1024 * 1024;
    volatile char *p = malloc(n);
    if (!p) { puts("malloc failed"); return 3; }
    for (size_t i = 0; i < n; i += 4096) p[i] = 1;
    puts("allocated");
    return 0;
}
'''

CASES = {
    "good": r'''#include <stdio.h>
int main(void) { int a, b; if (scanf("%d %d", &a, &b) != 2) return 1; printf("%d\n", a + b); return 0; }
''',
    "compile_error": "int main(void) { return 0 }\n",
    "infinite_loop": "int main(void) { for (;;); }\n",
    "segfault": "int main(void) { int *p = 0; *p = 1; return 0; }\n",
    "memory_hog": MEM_HOG,
    "fork_bomb": "#include <unistd.h>\nint main(void) { for (;;) fork(); }\n",
    "endless_output": "#include <stdio.h>\nint main(void) { for (;;) putchar(97); }\n",
}

tests = [{"id": "T001", "input": "7 5\n"}]

for name, src in CASES.items():
    res = sandbox.run_c(src, tests, time_limit_s=1, memory_limit_mb=64)
    if not res["compile"]["ok"]:
        print(f"{name:15} COMPILE FAILED: {res['compile']['stderr'].splitlines()[0]}")
        continue
    r = res["runs"][0]
    print(f"{name:15} rc={r['returncode']} signal={r['signal']} timed_out={r['timed_out']} "
          f"cpu={r['cpu_ms']}ms truncated={r['truncated']} stdout={r['stdout'][:15]!r}")
print("gcc", res["tool_versions"]["gcc"])