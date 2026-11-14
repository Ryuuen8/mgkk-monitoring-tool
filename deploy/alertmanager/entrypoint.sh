#!/bin/sh
# Render ${VAR} placeholders from the environment, then start Alertmanager.
# Alertmanager itself has no environment-expansion flag.
set -eu

template="${ALERTMANAGER_TEMPLATE:-/etc/alertmanager/alertmanager.yml.tmpl}"
target="${ALERTMANAGER_CONFIG:-/tmp/alertmanager.yml}"

cp "$template" "$target"
for name in \
    SMTP_SMARTHOST SMTP_USERNAME SMTP_PASSWORD SMTP_REQUIRE_TLS \
    ALERT_EMAIL_FROM ALERT_EMAIL_TO \
    SLACK_WEBHOOK_URL SLACK_CHANNEL ALERT_WEBHOOK_URL
do
    value=$(printenv "$name" || true)
    escaped=$(printf '%s' "$value" | sed -e 's/[\\&|]/\\&/g')
    sed -i "s|\${$name}|$escaped|g" "$target"
done

exec /bin/alertmanager \
    --config.file="$target" \
    --storage.path=/alertmanager
