ARG REGISTRY=ghcr.io/seg-way/containers/segway-connect-system-base-source
ARG VERSION=1.2.4
FROM $REGISTRY:$VERSION as builder

COPY python /app/plugin
RUN python3 -m venv /app/.venv ;\
    . /app/.venv/bin/activate ;\
    cd /app/plugin;\
    poetry install --no-dev -n

FROM $REGISTRY:$VERSION

ENV VIRTUAL_ENV=/app/.venv
COPY --from=builder /app/.venv /app/.venv
COPY etc/syslog-ng/conf.d/plugin /etc/syslog-ng/conf.d/plugin

COPY python/microsoft_azure_source_eventhub /etc/syslog-ng/python/microsoft_azure_source_eventhub
# USER ${uid}:${gid}
