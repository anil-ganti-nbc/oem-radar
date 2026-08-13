#!/usr/bin/env bash
# Double-click to launch the OEM Radar dashboard locally.
# Delegates entirely to mac/dashboard — no logic lives here.
cd "$(dirname "${BASH_SOURCE[0]}")"
exec mac/dashboard
