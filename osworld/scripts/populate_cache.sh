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
