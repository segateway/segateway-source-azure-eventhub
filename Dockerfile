FROM ghcr.io/seg-way/containers/segway-connect-system-base-source:1.2.4

COPY etc/syslog-ng/conf.d/plugin /etc/syslog-ng/conf.d/plugin

COPY python /app/plugin
RUN cd /app/plugin ;\
    poetry export --format requirements.txt >/usr/lib64/syslog-ng/python/requirements.txt ;\
    syslog-ng-update-virtualenv -y ;\
    pip cache purge ; rm -rf /app/plugin
COPY python/microsoft_azure_source_eventhub /etc/syslog-ng/python/microsoft_azure_source_eventhub
# USER ${uid}:${gid}
