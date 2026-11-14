FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext-base snmpd \
    && rm -rf /var/lib/apt/lists/*

COPY snmpd.conf.template /etc/snmp/snmpd.conf.template

CMD ["sh", "-c", "envsubst < /etc/snmp/snmpd.conf.template > /tmp/snmpd.conf && exec snmpd -f -Lo -C -c /tmp/snmpd.conf"]
