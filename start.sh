#!/bin/bash
# Start Truth with secrets from Infisical
# Usage: ./start.sh [docker compose args...]

set -euo pipefail

cd "$(dirname "$0")"

# Export secrets from Infisical, then run docker compose
exec infisical run --env=prod --path=/truth -- docker compose "$@"
