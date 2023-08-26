ARG REGISTRY=ghcr.io/segateway/containers/segateway-base-source
ARG BASEVERSION=3.0.0
FROM $REGISTRY:$BASEVERSION as builder

RUN apk add -U --upgrade --no-cache \
    python3-dev \
    libffi-dev ;\
    mkdir -p /app/plugin

COPY pyproject.toml /app/plugin
COPY microsoft_azure_eventhub_source /app/plugin/microsoft_azure_eventhub_source

RUN python3 -m venv /app/.venv ;\
    . /app/.venv/bin/activate ;\
    cd /app/plugin;\
    poetry install --only main -n

FROM $REGISTRY:$BASEVERSION

ENV VIRTUAL_ENV=/app/.venv
COPY --from=builder /app /app
COPY plugin.conf /etc/syslog-ng/conf.d/plugin/
USER ${uid}:${gid}
