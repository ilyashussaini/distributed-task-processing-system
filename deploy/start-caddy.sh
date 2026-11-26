#!/bin/sh
set -eu

export TASKFLOW_OPERATOR_HASH="$(cat /run/secrets/operator_hash)"
export TASKFLOW_API_TOKEN="$(cat /run/secrets/api_token)"
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
