#!/usr/bin/env bash
# Publish the Firebase Hosting site: static crawlable pages + rewrite of everything else to Cloud Run.
# Never publish a rewrite-only release: Googlebot cannot fetch pages through the rewrite (see deploy/cloudrun.md).
set -euo pipefail
cd "$(dirname "$0")/.."
exec ./.venv/bin/python -u scripts/firebase_deploy.py
