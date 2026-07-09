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

#!/bin/bash
# Pre-populate the OSWorld file cache from HuggingFace.
# Reads cache_manifest.txt (tab-separated: url, cache_path) and downloads each file.
set -euo pipefail

MANIFEST="$(dirname "$0")/cache_manifest.txt"
OSWORLD_DIR="${1:-/tmp/OSWorld}"
FAILED=0
TOTAL=0

while IFS=$'\t' read -r url cache_path; do
    TOTAL=$((TOTAL + 1))
    dest="${OSWORLD_DIR}/${cache_path}"
    mkdir -p "$(dirname "$dest")"
    if [ -f "$dest" ]; then
        continue
    fi
    if ! curl -fsSL --retry 3 --retry-delay 2 -o "$dest" "$url"; then
        echo "WARN: Failed to download $url" >&2
        FAILED=$((FAILED + 1))
        rm -f "$dest"
    fi
    if [ $((TOTAL % 50)) -eq 0 ]; then
        echo "Progress: $TOTAL files processed..."
    fi
done < "$MANIFEST"

echo "Cache populated: $TOTAL files, $FAILED failures"
