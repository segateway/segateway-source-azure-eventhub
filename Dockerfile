FROM ghcr.io/seg-way/segway-connect-system-base-source/container:1.1.2

COPY etc/syslog-ng/conf.d/plugin /etc/syslog-ng/conf.d/plugin

COPY python /app/python
RUN . /app/.venv/bin/activate ;\
    pushd /app/python ;\
    poetry export --format requirements.txt | pip --no-cache-dir install -r /dev/stdin
