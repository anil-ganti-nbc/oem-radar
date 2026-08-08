#!/bin/sh
# Container entrypoint. External scheduler invokes this via
# `docker compose run --rm oem-radar run`. No GUI/browser launch — the
# dashboard command is available but not the default and OEM_RADAR_OPEN_BROWSER=0.
set -eu
cd /app
mkdir -p "${OEM_RADAR_DATA_DIR:-/app/data}/http_cache" "${OEM_RADAR_DATA_DIR:-/app/data}/raw" 2>/dev/null || true
if [ "$#" -eq 0 ]; then
  exec oem-radar run
fi
case "$1" in
  oem-radar) shift; exec oem-radar "$@" ;;
  validate|run|status|coverage|dashboard|outbox|test-notify|probe|version|identity|health)
    exec oem-radar "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
