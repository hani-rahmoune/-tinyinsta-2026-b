#!/usr/bin/env bash
# PARTIE 3 — version corrigee : identique a fixed1 (1 instance, manual scaling,
# B1) MAIS gunicorn avec 2 workers x 8 threads au lieu du defaut (1 worker
# synchrone, 1 thread). HYPOTHESE testee en partie 3 : des threads permettraient
# de servir plusieurs requetes en parallele. Resultat : refutee (README, 2.3).
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
