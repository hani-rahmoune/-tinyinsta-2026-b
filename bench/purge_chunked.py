#!/usr/bin/env python3
"""Purge d'un jeu de donnees par petits paquets, pour eviter les timeouts."""
import sys
import time

from google.cloud import datastore
from google.cloud.datastore.query import PropertyFilter

project, prefix = sys.argv[1], sys.argv[2]
client = datastore.Client(project=project)
lo, hi = f"{prefix}_u", f"{prefix}_u\uffff"
total = 0


def read_page(kind):
    q = client.query(kind=kind)
    if kind == 'User':
        q.add_filter(filter=PropertyFilter('__key__', '>=', client.key('User', lo)))
        q.add_filter(filter=PropertyFilter('__key__', '<', client.key('User', hi)))
    else:
        q.add_filter(filter=PropertyFilter('author', '>=', lo))
        q.add_filter(filter=PropertyFilter('author', '<', hi))
    q.keys_only()
    return [e.key for e in q.fetch(limit=400)]


def retry(label, fn):
    for attempt in range(7):
        try:
            return fn()
        except Exception as e:
            print(f"  {label} KO ({type(e).__name__}), nouvel essai", flush=True)
            time.sleep(min(2 ** attempt, 30))
    sys.exit(f"{label}: abandon apres 7 essais")


for kind in ('Post', 'User'):
    while True:
        keys = retry('lecture', lambda: read_page(kind))
        if not keys:
            break
        retry('suppression', lambda: client.delete_multi(keys))
        total += len(keys)
        print(f"  {kind}: {total} supprimees", flush=True)

print(f"[{prefix}] {total} entites supprimees")
