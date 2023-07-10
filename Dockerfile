FROM ghcr.io/seg-way/segway-connect-system-base-source/container:1.1.4

COPY etc/syslog-ng/conf.d/plugin /etc/syslog-ng/conf.d/plugin

COPY python /app/plugin
RUN . /app/.venv/bin/activate ;\
    pushd /app/plugin ;\
    poetry install
