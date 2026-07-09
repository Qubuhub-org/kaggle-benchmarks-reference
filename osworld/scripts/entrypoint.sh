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
set -euo pipefail

# Validate required environment variables
missing=()
for var in MODEL_PROXY_API_KEY MODEL_PROXY_URL LLM_DEFAULT OSWORLD_TASK_DOMAIN OSWORLD_TASK_ID; do
    if [ -z "${!var:-}" ]; then
        missing+=("$var")
    fi
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "ERROR: Missing required environment variables: ${missing[*]}" >&2
    exit 1
fi

# Map model proxy vars to OpenAI env vars
export OPENAI_API_KEY="$MODEL_PROXY_API_KEY"
export OPENAI_BASE_URL="$MODEL_PROXY_URL"

# Generate task config
echo "{\"${OSWORLD_TASK_DOMAIN}\": [\"${OSWORLD_TASK_ID}\"]}" > /tmp/OSWorld/single_task.json

# Write Google OAuth credentials and account settings if env vars are set
GOOGLE_SETTINGS_DIR="/tmp/OSWorld/evaluation_examples/settings/google"
GOOGLEDRIVE_SETTINGS_DIR="/tmp/OSWorld/evaluation_examples/settings/googledrive"
mkdir -p "$GOOGLE_SETTINGS_DIR" "$GOOGLEDRIVE_SETTINGS_DIR"
if [ -n "${GOOGLE_OAUTH_CLIENT_ID:-}" ] && [ -n "${GOOGLE_OAUTH_CLIENT_SECRET:-}" ] && [ -n "${GOOGLE_PROJECT_ID:-}" ]; then
    # Google API client credentials (used by settings/google/)
    cat > "$GOOGLE_SETTINGS_DIR/credentials.json" <<CREDENTIALS_EOF
{
    "installed": {
        "client_id": "${GOOGLE_OAUTH_CLIENT_ID}",
        "project_id": "${GOOGLE_PROJECT_ID}",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "${GOOGLE_OAUTH_CLIENT_SECRET}",
        "redirect_uris": [
            "http://localhost"
        ]
    }
}
CREDENTIALS_EOF
    echo "Wrote Google OAuth credentials.json"

    # PyDrive client secrets (used by settings/googledrive/ for Google Drive tasks)
    cat > "$GOOGLEDRIVE_SETTINGS_DIR/client_secrets.json" <<PYDRIVE_EOF
{
    "installed": {
        "client_id": "${GOOGLE_OAUTH_CLIENT_ID}",
        "project_id": "${GOOGLE_PROJECT_ID}",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "${GOOGLE_OAUTH_CLIENT_SECRET}",
        "redirect_uris": [
            "http://localhost"
        ]
    }
}
PYDRIVE_EOF
    echo "Wrote PyDrive client_secrets.json"

    # Write saved OAuth token for PyDrive (avoids interactive browser auth)
    if [ -n "${GOOGLE_OAUTH_REFRESH_TOKEN:-}" ]; then
        cat > "$GOOGLEDRIVE_SETTINGS_DIR/credentials.json" <<TOKEN_EOF
{
    "_class": "OAuth2Credentials",
    "_module": "oauth2client.client",
    "access_token": null,
    "client_id": "${GOOGLE_OAUTH_CLIENT_ID}",
    "client_secret": "${GOOGLE_OAUTH_CLIENT_SECRET}",
    "id_token": null,
    "invalid": false,
    "refresh_token": "${GOOGLE_OAUTH_REFRESH_TOKEN}",
    "revoke_uri": "https://oauth2.googleapis.com/revoke",
    "scopes": ["https://www.googleapis.com/auth/drive"],
    "token_expiry": "2000-01-01T00:00:00Z",
    "token_uri": "https://oauth2.googleapis.com/token",
    "user_agent": null
}
TOKEN_EOF
        echo "Wrote PyDrive saved credentials (refresh token)"
    fi
fi
# Write DataImpulse proxy config if credentials are set
PROXY_SETTINGS_DIR="/tmp/OSWorld/evaluation_examples/settings/proxy"
mkdir -p "$PROXY_SETTINGS_DIR"
if [ -n "${DATAIMPULSE_USERNAME:-}" ] && [ -n "${DATAIMPULSE_PASSWORD:-}" ]; then
    cat > "$PROXY_SETTINGS_DIR/dataimpulse.json" <<PROXY_EOF
[
    {
        "host": "gw.dataimpulse.com",
        "port": 823,
        "username": "${DATAIMPULSE_USERNAME}",
        "password": "${DATAIMPULSE_PASSWORD}",
        "protocol": "http",
        "provider": "dataimpulse",
        "type": "residential",
        "country": "US",
        "note": "Dataimpulse Residential Proxy"
    }
]
PROXY_EOF
    echo "Wrote DataImpulse proxy config"
fi

if [ -n "${GOOGLE_ACCOUNT_EMAIL:-}" ] && [ -n "${GOOGLE_ACCOUNT_PASSWORD:-}" ]; then
    cat > "$GOOGLE_SETTINGS_DIR/settings.json" <<SETTINGS_EOF
{
    "email": "${GOOGLE_ACCOUNT_EMAIL}",
    "password": "${GOOGLE_ACCOUNT_PASSWORD}"
}
SETTINGS_EOF
    echo "Wrote Google account settings.json"
fi

# Start Docker daemon
dockerd --storage-driver=overlay2 > /tmp/docker_log.txt 2>&1 &
echo "Starting Docker daemon (PID: $!)..."

# Wait for Docker daemon to be ready
for i in $(seq 1 30); do
    if docker info > /dev/null 2>&1; then
        echo "Docker daemon is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Docker daemon failed to start. Check /tmp/docker_log.txt" >&2
        exit 1
    fi
    sleep 1
done

# Run the OSWorld task, capturing exit code so post_task always runs
cd /tmp/OSWorld
export TASK_EXIT_CODE=0
/tmp/osworld_env/bin/python3 scripts/python/run_multienv.py \
    --test_all_meta_path single_task.json \
    --headless \
    --provider_name docker \
    --model "$LLM_DEFAULT" \
    --client_password password \
    --domain "$OSWORLD_TASK_DOMAIN" \
    2>&1 | tee /tmp/osworld_output.txt || TASK_EXIT_CODE=$?

echo "Task exited with code: $TASK_EXIT_CODE"

# Run post-task script regardless of task outcome
if [ -x /opt/scripts/post_task.sh ]; then
    cd "${OSWORLD_FINAL_RESULTS_PATH:-/kaggle/working}"
    /opt/scripts/post_task.sh
fi
