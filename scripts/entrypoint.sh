#!/bin/sh
set -eu
cd /app
if [ -n "${OEM_RADAR_DATA_DIR:-}" ]; then
  mkdir -p "$OEM_RADAR_DATA_DIR/http_cache" "$OEM_RADAR_DATA_DIR/raw" 2>/dev/null || true
fi
if [ "$#" -eq 0 ]; then
  exec oem-radar run
fi
case "$1" in
  oem-radar)
    shift
    exec oem-radar "$@"
    ;;
  validate|run|status|dashboard|outbox|test-notify|probe|version|identity|health)
    exec oem-radar "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
