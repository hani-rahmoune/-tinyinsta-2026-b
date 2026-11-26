#!/usr/bin/env bash
# Premier essai, abandonne : echec sur u10000 (DeadlineExceeded).
# Le script utilise pour la campagne est bench/seed_order.sh.
# Genere les 26 jeux de donnees du sujet (~400 000 entites, quelques minutes, <1 $).
#   P=<mon-projet> ./bench/seed_essai1.sh
# ATTENTION : ne JAMAIS relancer un prefixe deja genere (les posts s ajoutent).
# Pour refaire un jeu : python bench/seed_exact.py --project $P --prefix <x> --purge
set -euo pipefail
: "${P:?il faut definir P, identifiant du projet GCP}"
cd "$(dirname "$0")/.."
S="python bench/seed_exact.py --project $P"

$S --prefix base   --users 1000  --posts-per-user 20 --followees 20
$S --prefix u100   --users 100   --posts-per-user 20 --followees 20
$S --prefix u10000 --users 10000 --posts-per-user 20 --followees 20
for p in 10 100 1000; do
  $S --prefix "p$p" --users 100 --posts-per-user "$p" --followees 20
done
for f in $(seq 5 5 100); do
  $S --prefix "$(printf 'f%02d' "$f")" --users 120 --posts-per-user 20 --followees "$f"
done
echo "26 jeux generes."
