#!/bin/bash
# Poll helper for the 2026-08-24 kafka sweep rerun (read-only).
cd /home/freerat/projects/topotestix
dirs=$(ls -d .topotestix/runs/*kafka-cluster-sweep-1-50-rerun-20260824 2>/dev/null | wc -l)
latest=$(ls -dt .topotestix/runs/*kafka-cluster-sweep-1-50-rerun-20260824 2>/dev/null | head -1)
now=$(date -u +%s)
if [ -n "$latest" ]; then
  mt=$(stat -c %Y "$latest")
  age=$(( (now-mt)/60 ))
else
  age=-1
fi
alive=$(ps aux | grep "orchestrator sweep kafka-cluster" | grep -v grep | wc -l)
echo "$(date -u +%H:%M:%S) dirs=$dirs alive=$alive newest=$(basename "$latest" 2>/dev/null) age_min=$age"
