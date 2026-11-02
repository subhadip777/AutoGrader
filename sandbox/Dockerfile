# AutoGrader sandbox image: gcc, sanitizers, valgrind and cppcheck, plus the runner.
# Build:  docker build -t autograder-sandbox:2 sandbox
# The host starts it with --network none, --read-only, --cap-drop ALL (+SETUID/SETGID/KILL/DAC_OVERRIDE),
# memory/cpu/pids limits; the runner then executes student code as the user "nobody".
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev libasan8 libubsan1 python3 valgrind cppcheck \
 && rm -rf /var/lib/apt/lists/*

COPY runner.py /opt/runner.py
LABEL org.autograder.protocol="2"

WORKDIR /
ENTRYPOINT ["python3", "/opt/runner.py"]
