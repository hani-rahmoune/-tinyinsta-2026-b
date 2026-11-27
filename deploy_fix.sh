#!/usr/bin/env bash
# Partie 3 : version fix1, identique a fixed1 (B1, 1 instance, manual scaling)
# sauf gunicorn, lance avec 2 workers x 8 threads au lieu d'un worker synchrone.
#
#   ./deploy_fix.sh
#   URL=$(gcloud app versions describe fix1 --service default --format='value(versionUrl)')
#   URL=$URL N=1 TAG=p3 ./bench/run_sweep.sh
#   gcloud app versions stop fix1
set -euo pipefail
cd "$(dirname "$0")"
YAML="app-fix1.yaml"
trap 'rm -f "$YAML"' EXIT
cat > "$YAML" <<EOF
runtime: python312
entrypoint: gunicorn -b :\$PORT --workers 2 --threads 8 main:app

instance_class: B1
manual_scaling:
  instances: 1

handlers:
- url: /
  script: auto
env_variables:
  SEED_TOKEN: "change-me-seed-token"
EOF
gcloud app deploy "$YAML" --version fix1 --no-promote --quiet "$@"
