#!/usr/bin/env bash
# deploy_frontend.sh
# ------------------
# Builds the frontend SPA and ships it to the production VM's nginx docroot.
# This fills the gap noted in GCP_DEPLOYMENT.md §0: "How the built
# frontend/dist reaches production ... is not captured in version control."
#
# Prerequisites: node/npm on the build machine, rsync over SSH to the VM, and
# the nginx site config from deploy/nginx/zoiko-payroll.conf installed with
# `root /var/www/zoiko-payroll/frontend/dist;`.
#
# Usage:
#   HOST=user@vm.example.com bash deploy/scripts/deploy_frontend.sh
#
# Overridable env vars:
#   HOST                  SSH target (required)
#   REMOTE_DIST=/var/www/zoiko-payroll/frontend/dist
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE_DIST="${REMOTE_DIST:-/var/www/zoiko-payroll/frontend/dist}"

if [ -z "${HOST:-}" ]; then
  echo "!! HOST is required, e.g. HOST=user@vm.example.com bash $0" >&2
  exit 1
fi

echo "==> Building frontend from $ROOT/frontend"
cd "$ROOT/frontend"
npm ci
npm run build

echo "==> Rsyncing frontend/dist to ${HOST}:${REMOTE_DIST}"
rsync -avz --delete "$ROOT/frontend/dist/" "${HOST}:${REMOTE_DIST}/"

echo "==> Done."