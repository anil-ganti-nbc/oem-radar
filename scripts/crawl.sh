#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p data
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) crawl start" >> data/crawl-runs.log
oem-radar run >> data/crawl-runs.log 2>&1
ec=$?
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) crawl done (exit $ec)" >> data/crawl-runs.log
exit $ec
