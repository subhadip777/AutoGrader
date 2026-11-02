FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev python3 \
 && rm -rf /var/lib/apt/lists/*

COPY runner.py /opt/runner.py

WORKDIR /
ENTRYPOINT ["python3", "/opt/runner.py"]