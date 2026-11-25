#!/usr/bin/env bash
# Partie 1 — coût d'une requête. Version fixed1, UNE requête à la fois (-u 1).
#
#   URL=$(gcloud app versions describe fixed1 --service default --format='value(versionUrl)')
#   URL=$URL ./bench/run_part1.sh
#
# 26 runs (3 U + 3 P + 20 F) d'environ 45 s = ~25 min.
# Reprise automatique : un run dont le CSV existe déjà est sauté.
set -euo pipefail
: "${URL:?usage: URL=https://fixed1-dot-... ./bench/run_part1.sh}"
cd "$(dirname "$0")/.."
DUR="${DUR:-45s}"
mkdir -p raw

# Garde-fou n°1 : on interroge bien la bonne version (sinon App Engine renvoie
# silencieusement la version par défaut, sans en-tête X-Instance).
if ! curl -sI "$URL/api/timeline?user=base_u00001" | grep -qi '^x-instance'; then
  echo "ERREUR : pas d'en-tête X-Instance sur $URL" >&2
  echo "         -> mauvaise URL, ou version arrêtée. Campagne annulée." >&2
  exit 1
fi
echo "OK : $URL répond avec X-Instance / Server-Timing"

run() {   # run <nom_du_log> <prefixe_du_jeu> <U_du_jeu>
  local log="raw/$1.csv" prefix="$2" nusers="$3"
  if [ -s "$log" ]; then echo "-- saute $log (déjà mesuré)"; return 0; fi
  echo "== $log   prefix=$prefix  U=$nusers  durée=$DUR"
  TINY_PREFIX="$prefix" TINY_USERS="$nusers" TINY_LIMIT=20 TINY_LOG="$log" \
    python -m locust -f bench/locustfile.py --headless \
      -u 1 -r 1 -t "$DUR" --only-summary --exit-code-on-error 0 --host "$URL"
}

# --- Facteur U (P=20, F=20) ---------------------------------------------
run p1_u_100   u100   100
run p1_u_1000  base   1000
run p1_u_10000 u10k 10000

# --- Facteur P (U=100, F=20) --------------------------------------------
# NB : p1_u_100 ci-dessus EST le point P=20 de cette série (U=100, F=20).
run p1_p_10   p10   100
run p1_p_100  p100  100
run p1_p_1000 p1000 100

# --- Facteur F (U=120, P=20), 20 valeurs --------------------------------
for f in $(seq 5 5 100); do
  run "p1_f_${f}" "$(printf 'f%02d' "$f")" 120
done

echo
echo "Partie 1 terminée. N'OUBLIEZ PAS : gcloud app versions stop fixed1"
