#!/bin/bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
