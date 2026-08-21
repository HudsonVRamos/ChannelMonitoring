#!/bin/bash
cd ~/ChannelMonitoring
git pull -q
pkill -f chrome 2>/dev/null
sleep 2
export POC_CHANNEL_URL=https://www.skymais.com.br/player/live/CH0100000000124
export POC_LOG_LEVEL=INFO
export POC_OUTPUT_DIR=./output
export POC_DRM_TIMEOUT=60
export POC_TELEMETRY_DURATION=10
export POC_STORAGE_STATE_PATH=dummy
export CHROME_PROFILE_DIR=/data/chrome-profile
mkdir -p output
timeout 120 xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" python3 -m src
echo "EXIT_CODE=$?"
echo "=== REPORT ==="
cat output/poc_report.json 2>/dev/null || echo "NO_REPORT"
