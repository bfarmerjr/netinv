#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# NetInv — Copyright (C) 2026 Bill Farmer, Jr. See LICENSE.
# Start NetInv with gunicorn. Settings come from netinv.conf next to this
# script (copy netinv.conf.example), overridable from the environment:
#   NETINV_HOST (default 127.0.0.1)  listen IP; IPv6 is fine, e.g. ::1 or ::
#   NETINV_PORT (default 8000)       listen TCP port
#   NETINV_BIND                      full gunicorn bind (e.g. unix:/run/netinv.sock);
#                                    if set, overrides NETINV_HOST/NETINV_PORT
#   NETINV_WORKERS (default 2), NETINV_THREADS (default 8),
#   NETINV_DATA_DIR (default ./instance), NETINV_PROXY_HOPS (default 1)
# Threaded workers so idle keep-alive/preconnect sockets (e.g. from
# Chromium) can't tie up every worker and stall other requests.
cd "$(dirname "$0")"
if [ -f netinv.conf ]; then
  # Variables already set in the environment take precedence over netinv.conf.
  _env=$(export -p)
  set -a
  . ./netinv.conf
  set +a
  eval "$_env"
fi
: "${NETINV_HOST:=127.0.0.1}" "${NETINV_PORT:=8000}" "${NETINV_WORKERS:=2}" "${NETINV_THREADS:=8}"
if [ -z "${NETINV_BIND:-}" ]; then
  case "$NETINV_HOST" in
    *:*) NETINV_BIND="[$NETINV_HOST]:$NETINV_PORT" ;;  # IPv6 needs brackets
    *)   NETINV_BIND="$NETINV_HOST:$NETINV_PORT" ;;
  esac
fi
export NETINV_BIND NETINV_WORKERS NETINV_THREADS  # shown in the footer and About page
exec .venv/bin/gunicorn \
  --bind "$NETINV_BIND" \
  --workers "$NETINV_WORKERS" \
  --worker-class gthread \
  --threads "$NETINV_THREADS" \
  --access-logfile - \
  "netinv:create_app()"
