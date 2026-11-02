"""The sandbox runs untrusted C under limits and reports what happened."""
import os

import pytest

from server import sandbox

ADD = '#include <stdio.h>\nint main(void){int a,b; if(scanf("%d %d",&a,&b)!=2) return 1; printf("%d\\n",a+b); return 0;}\n'
ONE = [{"id": "T1", "input": "7 5\n"}]


def run(src, tests=ONE, **kw):
    kw.setdefault("time_limit_s", 1)
    kw.setdefault("memory_limit_mb", 64)
    return sandbox.run_c(src, tests, **kw)


def test_good_program(sandbox_ok):
    res = run(ADD)
    r = res["runs"][0]
    assert res["compile"]["ok"] and r["returncode"] == 0 and r["stdout"] == "12\n"
    assert res["tool_versions"]["gcc"] and res["protocol"] == 2
    assert res["isolation"] == "nobody"          # student code never runs as root


def test_compile_error_is_reported(sandbox_ok):
    res = run("int main(void) { return 0 }\n")
    assert not res["compile"]["ok"] and "error" in res["compile"]["stderr"]
    assert res["runs"][0]["skipped"]


def test_infinite_loop_is_killed(sandbox_ok):
    r = run("int main(void) { for (;;); }\n")["runs"][0]
    assert r["timed_out"] or r["signal"] in ("SIGKILL", "SIGXCPU")
    assert r["wall_ms"] < 6000


def test_segfault_is_reported(sandbox_ok):
    r = run("int main(void) { int *p = 0; *p = 1; return 0; }\n")["runs"][0]
    assert r["signal"] == "SIGSEGV"


def test_memory_limit(sandbox_ok):
    src = ('#include <stdio.h>\n#include <stdlib.h>\nint main(void){ size_t n = 400u<<20; volatile char *p = malloc(n);'
           ' if(!p){puts("malloc failed"); return 3;} for(size_t i=0;i<n;i+=4096) p[i]=1; puts("allocated"); return 0;}\n')
    r = run(src)["runs"][0]
    assert r["stdout"] != "allocated\n"
    assert r["returncode"] != 0


def test_fork_bomb_is_contained(sandbox_ok):
    r = run("#include <unistd.h>\nint main(void){ for(;;) fork(); }\n")["runs"][0]
    assert r["timed_out"] or r["returncode"] != 0


def test_output_flood_is_cut(sandbox_ok):
    r = run('#include <stdio.h>\nint main(void){ for(;;) putchar(97); }\n')["runs"][0]
    assert r["signal"] == "SIGXFSZ" and r["truncated"] and len(r["stdout"]) <= 64 * 1024


def test_cannot_read_root_only_files(sandbox_ok):
    src = '#include <stdio.h>\nint main(void){ FILE *f = fopen("/etc/shadow","r"); puts(f ? "OPENED" : "denied"); return 0; }\n'
    assert run(src)["runs"][0]["stdout"] == "denied\n"


@pytest.mark.skipif(os.getenv("AUTOGRADER_SANDBOX", "docker") != "docker", reason="network isolation needs the Docker backend")
def test_no_network(sandbox_ok):
    src = ('#include <stdio.h>\n#include <sys/socket.h>\n#include <netinet/in.h>\n#include <arpa/inet.h>\n#include <unistd.h>\n'
           'int main(void){ int s = socket(AF_INET, SOCK_STREAM, 0); struct sockaddr_in a = {0}; a.sin_family = AF_INET;'
           ' a.sin_port = htons(53); inet_pton(AF_INET, "1.1.1.1", &a.sin_addr);'
           ' puts(connect(s, (struct sockaddr*)&a, sizeof a) == 0 ? "CONNECTED" : "blocked"); return 0; }\n')
    assert run(src)["runs"][0]["stdout"] == "blocked\n"


def test_disallowed_flags_rejected_before_running():
    with pytest.raises(ValueError):
        sandbox.split_flags("-Wall -o /tmp/x")
    with pytest.raises(ValueError):
        sandbox.split_flags(["-fplugin=/tmp/evil.so"])
    assert sandbox.split_flags("-Wall -Wextra -Werror -std=c11") == ["-Wall", "-Wextra", "-Werror", "-std=c11"]


def test_runner_rejects_bad_flags_and_workdir(sandbox_ok):
    with pytest.raises(sandbox.SandboxError, match="not allowed"):
        sandbox.execute({"source": ADD, "builds": [{"name": "main", "flags": ["-Wl,--wrap=main"]}], "runs": []})


def test_missing_docker_fails_safely(monkeypatch):
    """With the Docker backend and no docker binary, nothing runs on the host."""
    monkeypatch.setenv("AUTOGRADER_SANDBOX", "docker")
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    with pytest.raises(sandbox.SandboxUnavailable, match="Docker is not installed"):
        sandbox.execute({"source": ADD, "builds": [{"name": "main", "flags": ["-O2"]}], "runs": []})
    st = sandbox.status(refresh=True)
    assert not st["available"] and "Docker" in st["detail"]
    sandbox._status_cache.clear()


def test_unknown_backend_is_refused(monkeypatch):
    monkeypatch.setenv("AUTOGRADER_SANDBOX", "host")
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.backend()


def test_docker_command_is_locked_down():
    cmd = sandbox._docker_cmd("ag-test")
    joined = " ".join(cmd)
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "--pids-limit", "--memory",
                 "--cpus", "no-new-privileges", "--rm"):
        assert flag in joined
    assert "--privileged" not in joined
