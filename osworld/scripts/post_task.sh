#!/bin/bash
set -euo pipefail

# Copy task result screenshots to results root
RESULTS_ROOT="${OSWORLD_FINAL_RESULTS_PATH:-/kaggle/working}"
results_dir="/tmp/OSWorld/results/pyautogui/screenshot/${LLM_DEFAULT}/${OSWORLD_TASK_DOMAIN}/${OSWORLD_TASK_ID}"
if [ -d "$results_dir" ]; then
    cp -r "$results_dir"/. "$RESULTS_ROOT"/
    echo "Copied results from $results_dir to $RESULTS_ROOT"
else
    echo "WARNING: Results directory not found: $results_dir" >&2
fi

# Fetch model proxy logs and build task.run.json
python3 /opt/scripts/build_run_json.py
