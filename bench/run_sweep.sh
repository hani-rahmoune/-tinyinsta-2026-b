#!/usr/bin/env bash
# Balayage de concurrence C in {1,2,4,8,16,32,64} sur une version donnee.
# Sert pour la partie 2 (TAG=p2) et pour la re-mesure de la partie 3 (TAG=p3).
#
#   URL=$(gcloud app versions describe fixed1 --service default --format='value(versionUrl)')
#   URL=$URL N=1 ./bench/run_sweep.sh              # partie 2, N=1
#   URL=$URL N=2 ./bench/run_sweep.sh              # partie 2, N=2
#   URL=$URL N=1 TAG=p3 ./bench/run_sweep.sh       # partie 3, version corrigee
#
# 7 runs de 75 s = ~10 min. Reprise automatique : un CSV deja present est saute.
set -euo pipefail
: "${URL:?il faut definir URL}"
: "${N:?il faut definir N, le nombre d instances fixes de la version mesuree}"
cd "$(dirname "$0")/.."
TAG="${TAG:-p2}"
DUR="${DUR:-75s}"
mkdir -p raw

if ! curl -sI "$URL/api/timeline?user=base_u00001" | grep -qi '^x-instance'; then
  echo "ERREUR : pas d'en-tete X-Instance sur $URL -> mauvaise URL ?" >&2
  exit 1
fi
echo "OK : $URL  (TAG=$TAG, N=$N)"

for c in 1 2 4 8 16 32 64; do
  log="raw/${TAG}_n${N}_c${c}.csv"
  if [ -s "$log" ]; then echo "-- saute $log (deja mesure)"; continue; fi
  echo "== $log   C=$c  duree=$DUR"
  TINY_PREFIX=base TINY_USERS=1000 TINY_LIMIT=20 TINY_LOG="$log" \
    python -m locust -f bench/locustfile.py --headless \
      -u "$c" -r "$c" -t "$DUR" --only-summary --exit-code-on-error 0 --host "$URL"
done

echo
echo "Balayage $TAG N=$N termine. ARRETEZ la version : gcloud app versions stop <version>"
