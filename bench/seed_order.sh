#!/usr/bin/env bash
# Ordre utilise pour le re-seeding apres l'echec (DeadlineExceeded) du premier
# seeding de u10000 : petits jeux d'abord, les deux gros a la fin avec moins
# de threads. Le jeu U=10000 porte le prefixe u10k (voir README, section 1).
set -euo pipefail
cd "$(dirname "$0")/.."
S="python bench/seed_exact.py --project tinyinsta-b"

$S --prefix u100 --users 100 --posts-per-user 20 --followees 20
for f in $(seq 5 5 100); do
  $S --prefix "$(printf 'f%02d' "$f")" --users 120 --posts-per-user 20 --followees "$f"
done
$S --prefix p10  --users 100 --posts-per-user 10  --followees 20
$S --prefix p100 --users 100 --posts-per-user 100 --followees 20
$S --prefix base --users 1000 --posts-per-user 20 --followees 20
$S --prefix p1000  --users 100   --posts-per-user 1000 --followees 20 --threads 3
$S --prefix u10k   --users 10000 --posts-per-user 20 --followees 20 --threads 3
echo "26 jeux OK"
