#!/usr/bin/env python3
"""Vérifications de validité : tout ce que le rapport affirme sur la plateforme
est MESURÉ ici, sur le projet, plutôt que supposé.

  python3 bench/verify.py            (depuis la racine du dépôt, dans Cloud Shell)

Écrit les preuves brutes dans raw/verify/ et un résumé lisible sur la sortie.

  A. chemin de code réellement exécuté par get_timeline (main.py), entités lues
     par timeline, et limite du filtre IN mesurée (30 vs 31 valeurs) ;
  B. état de la plateforme : région, base, index, versions, budget, outils ;
  C. démarrages / arrêts des versions (journaux d'audit) -> heures d'instance ;
  D. configuration gunicorn réellement démarrée (journaux fixed1 / fix1) ;
  E. pendingTime App Engine (attente AVANT l'instance) pendant chaque run ;
  F. lectures / écritures Datastore et heures d'instance (Cloud Monitoring) ;
  G. grille tarifaire officielle (Cloud Billing Catalog API).
"""
import csv, glob, json, os, statistics, subprocess, sys, traceback
import urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "raw", "verify")
os.makedirs(OUT, exist_ok=True)


def sh(*args):
    r = subprocess.run(args, capture_output=True, text=True)
    return (r.stdout if r.returncode == 0 else "ERREUR: " + r.stderr).strip()


PROJECT = os.environ.get("PROJECT") or sh("gcloud", "config", "get-value", "project")
os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT
START = "2026-11-23T00:00:00Z"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
VERSION_OF = {"p1": "fixed1", "p2_n1": "fixed1", "p2_n2": "fixed2",
              "p2_n4": "fixed4", "p3_n1": "fix1"}


def save(name, obj):
    with open(os.path.join(OUT, name), "w") as f:
        if isinstance(obj, str):
            f.write(obj + "\n")
        else:
            json.dump(obj, f, indent=1, default=str)


def section(t):
    print("\n" + "=" * 78 + "\n" + t + "\n" + "=" * 78, flush=True)


def guarded(fn):
    def run():
        try:
            fn()
        except Exception:
            print("  !! section en échec :\n" + traceback.format_exc(limit=3))
    return run


_TOKEN = None


def api(url):
    global _TOKEN
    _TOKEN = _TOKEN or sh("gcloud", "auth", "print-access-token")
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + _TOKEN, "x-goog-user-project": PROJECT})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def run_windows():
    """(fichier, version, début, fin) de chaque run, d'après raw/*.csv."""
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "raw", "*.csv"))):
        name = os.path.basename(p)[:-4]
        key = "p1" if name.startswith("p1_") else name.rsplit("_c", 1)[0]
        with open(p) as f:
            ts = [float(r["T_START"]) for r in csv.DictReader(f)]
        out.append((name, VERSION_OF.get(key), min(ts), max(ts)))
    return out


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ----------------------------------------------------------------------- A
@guarded
def code_path():
    section("A. Chemin de code de get_timeline (main.py), mesuré")
    sys.path.insert(0, ROOT)
    import google.cloud.datastore as ds
    from google.cloud.datastore import query as dq
    import main

    print(f"google-cloud-datastore {ds.__version__}  |  "
          f"hasattr(client, 'gql') = {hasattr(main.client, 'gql')}  "
          f"(False => la branche GQL main.py:52-56 n'est jamais exécutée)")

    st = {}
    orig_fetch = dq.Query.fetch

    def fetch(self, *a, **k):
        st["queries"] += 1
        try:
            for e in orig_fetch(self, *a, **k):
                st["query_entities"] += 1
                yield e
        except Exception as ex:
            st["failed"] += 1
            st["error"] = f"{type(ex).__name__}: {str(ex)[:300]}"
            raise
    dq.Query.fetch = fetch

    orig_get = main.client.get

    def get(key, *a, **k):
        st["lookups"] += 1
        e = orig_get(key, *a, **k)
        st["lookup_entities"] += e is not None
        return e
    main.client.get = get

    rows = []
    for prefix in ["base", "u100", "u10k", "p10", "p100", "p1000",
                   "f05", "f25", "f30", "f50", "f100"]:
        user = f"{prefix}_u00000"
        st.update(queries=0, failed=0, query_entities=0, lookups=0,
                  lookup_entities=0, error="")
        tl = main.get_timeline(user, 20)
        ent = orig_get(main.client.key("User", user))
        F = len(ent.get("follows", [])) if ent else None
        path = ("IN (main.py:61-64)" if st["queries"] == 1 and not st["failed"]
                else "repli par auteur (main.py:66-72)")
        rows.append(dict(prefix=prefix, F=F, authors=len({*(ent or {}).get("follows", []), user}),
                         path=path, queries_ok=st["queries"] - st["failed"],
                         queries_failed=st["failed"], lookups=st["lookups"],
                         entities_read=st["lookup_entities"] + st["query_entities"],
                         returned=len(tl), error=st["error"]))
    print(f"{'jeu':6} {'F':>4} {'auteurs':>7}  {'chemin':34} {'req.ok':>6} "
          f"{'req.err':>7} {'entités lues':>12} {'renvoyés':>8}")
    for r in rows:
        print(f"{r['prefix']:6} {r['F']!s:>4} {r['authors']:>7}  {r['path']:34} "
              f"{r['queries_ok']:>6} {r['queries_failed']:>7} {r['entities_read']:>12} "
              f"{r['returned']:>8}")
    errs = {r["error"] for r in rows if r["error"]}
    for e in errs:
        print("  exception avalée par main.py:65 ->", e)
    with open(os.path.join(OUT, "reads_per_timeline.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

    # Limite du IN, mesurée directement : 30 puis 31 valeurs.
    dq.Query.fetch = orig_fetch
    ent = orig_get(main.client.key("User", "f30_u00000"))
    authors = sorted({*ent["follows"], "f30_u00000"})
    lim = []
    for n in (30, 31):
        try:
            q = main.client.query(kind="Post")
            q.add_filter("author", "IN", authors[:n])   # comme main.py:62
            q.order = ["-created"]
            res = f"OK, {len(list(q.fetch(limit=20)))} entités"
        except Exception as ex:
            res = f"ÉCHEC {type(ex).__name__}: {str(ex)[:300]}"
        lim.append(dict(values=n, result=res))
        print(f"  IN avec {n} valeurs -> {res}")
    save("in_limit.json", lim)


# ----------------------------------------------------------------------- B
@guarded
def platform():
    section("B. État de la plateforme")
    cmds = {
        "app": ["gcloud", "app", "describe", "--format=value(locationId,servingStatus)"],
        "database": ["gcloud", "firestore", "databases", "describe", "--database=(default)",
                     "--format=value(locationId,type,createTime)"],
        "indexes": ["gcloud", "datastore", "indexes", "list",
                    "--format=value(kind,properties.list(),state)"],
        "versions": ["gcloud", "app", "versions", "list",
                     "--format=value(id,traffic_split,last_deployed_time.datetime,serving_status)"],
        "billing_account": ["gcloud", "billing", "projects", "describe", PROJECT,
                            "--format=value(billingAccountName,billingEnabled)"],
        "locust": [sys.executable, "-m", "locust", "--version"],
        "python": [sys.executable, "--version"],
    }
    res = {k: sh(*v) for k, v in cmds.items()}
    acct = res["billing_account"].split()[0].split("/")[-1] if res["billing_account"] else ""
    if acct and not acct.startswith("ERREUR"):
        res["budgets"] = sh("gcloud", "billing", "budgets", "list", f"--billing-account={acct}",
                            "--format=value(displayName,amount.specifiedAmount.units,"
                            "amount.specifiedAmount.currencyCode)")
    for k, v in res.items():
        print(f"{k:16} {v}")
    save("platform.json", res)


# ----------------------------------------------------------------------- C
@guarded
def version_events():
    section("C. Créations / démarrages / arrêts de versions (journaux d'audit)")
    raw = sh("gcloud", "logging", "read",
             'protoPayload.serviceName="appengine.googleapis.com" AND '
             '(protoPayload.methodName:"CreateVersion" OR protoPayload.methodName:"UpdateVersion" '
             'OR protoPayload.methodName:"DeleteVersion")',
             "--freshness=30d", "--limit=500", "--format=json")
    if raw.startswith("ERREUR"):
        print(raw); return
    ev = json.loads(raw or "[]")
    save("version_events.json", ev)

    def find(o, key):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == key:
                    return v
                r = find(v, key)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = find(v, key)
                if r is not None:
                    return r
        return None
    for e in sorted(ev, key=lambda e: e["timestamp"]):
        pp = e.get("protoPayload", {})
        first = (e.get("operation") or {}).get("first")
        if first is False:
            continue  # une ligne par opération (la première)
        print(f"{e['timestamp'][:19]}  {pp.get('methodName','').split('.')[-1]:14} "
              f"{pp.get('resourceName','').split('/')[-1]:18} "
              f"servingStatus={find(pp.get('request', {}), 'servingStatus')}")


# ----------------------------------------------------------------------- D
@guarded
def gunicorn():
    section("D. Configuration gunicorn réellement démarrée")
    for v in ("fixed1", "fix1"):
        raw = sh("gcloud", "logging", "read",
                 f'resource.type="gae_app" AND resource.labels.version_id="{v}" AND '
                 '(textPayload:"Booting worker" OR textPayload:"Using worker" OR '
                 'textPayload:"Listening at" OR textPayload:"Starting gunicorn")',
                 "--freshness=30d", "--limit=200", "--format=json(timestamp,textPayload)")
        ev = json.loads(raw) if raw and not raw.startswith("ERREUR") else []
        save(f"gunicorn_{v}.json", ev)
        lines = sorted((e["timestamp"][:19], e.get("textPayload", "").strip()) for e in ev)
        boots = sum("Booting worker" in t for _, t in lines)
        print(f"-- {v} : {len(lines)} lignes, {boots} 'Booting worker'")
        for ts, t in lines[:8]:
            print(f"   {ts}  {t[:110]}")


# ----------------------------------------------------------------------- E
def dur(s):
    return float(s.rstrip("s")) * 1000 if isinstance(s, str) and s.endswith("s") else None


@guarded
def pending():
    section("E. Journaux de requêtes App Engine : attente AVANT l'instance (pendingTime)")
    print(f"{'run':14} {'version':7} {'requêtes':>8} {'instances':>9} "
          f"{'latence méd. (ms)':>17} {'pendingTime méd. (ms)':>21} {'avec pending':>12}")
    rows = []
    for name, version, t0, t1 in run_windows():
        if not name.startswith(("p2_", "p3_")):
            continue
        flt = (f'resource.type="gae_app" AND resource.labels.version_id="{version}" AND '
               f'logName="projects/{PROJECT}/logs/appengine.googleapis.com%2Frequest_log" AND '
               f'timestamp>="{iso(t0 + 10)}" AND timestamp<="{iso(t1 + 5)}"')
        raw = sh("gcloud", "logging", "read", flt, "--limit=10000", "--freshness=30d",
                 "--format=json(protoPayload.latency,protoPayload.pendingTime,"
                 "protoPayload.instanceId,protoPayload.status)")
        if raw.startswith("ERREUR"):
            print(name, raw[:200]); continue
        ev = [e.get("protoPayload", {}) for e in json.loads(raw or "[]")]
        lat = [d for d in (dur(p.get("latency")) for p in ev) if d is not None]
        pen = [d for d in (dur(p.get("pendingTime")) for p in ev) if d is not None]
        r = dict(run=name, version=version, requests=len(ev),
                 instances=len({p.get("instanceId") for p in ev if p.get("instanceId")}),
                 latency_ms_median=round(statistics.median(lat), 1) if lat else None,
                 pending_ms_median=round(statistics.median(pen), 1) if pen else None,
                 with_pending=len(pen))
        rows.append(r)
        print(f"{name:14} {version:7} {r['requests']:>8} {r['instances']:>9} "
              f"{r['latency_ms_median']!s:>17} {r['pending_ms_median']!s:>21} {len(pen):>12}",
              flush=True)
    if rows:
        with open(os.path.join(OUT, "pending_time.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)


# ----------------------------------------------------------------------- F
def series(metric, aligner, period, extra=""):
    q = {"filter": f'metric.type="{metric}"{extra}', "interval.startTime": START,
         "interval.endTime": NOW, "aggregation.alignmentPeriod": f"{period}s",
         "aggregation.perSeriesAligner": aligner}
    out, tok = [], None
    while True:
        if tok:
            q["pageToken"] = tok
        r = api("https://monitoring.googleapis.com/v3/projects/"
                f"{PROJECT}/timeSeries?" + urllib.parse.urlencode(q))
        out += r.get("timeSeries", [])
        tok = r.get("nextPageToken")
        if not tok:
            return out


def val(p):
    v = p["value"]
    if "distributionValue" in v:
        return float(v["distributionValue"].get("count", 0))
    return float(v.get("int64Value", v.get("doubleValue", 0)))


@guarded
def usage():
    section("F. Consommation mesurée (Cloud Monitoring), par jour UTC")
    res = {}
    for metric in ("datastore.googleapis.com/entity/read_sizes",
                   "datastore.googleapis.com/entity/write_sizes",
                   "datastore.googleapis.com/api/request_count",
                   "firestore.googleapis.com/document/read_count",
                   "firestore.googleapis.com/document/write_count",
                   "firestore.googleapis.com/document/delete_count"):
        try:
            ts = series(metric, "ALIGN_DELTA", 86400)
        except Exception as ex:
            print(f"{metric}: indisponible ({ex})"); continue
        agg = defaultdict(float)
        for s in ts:
            lab = ",".join(f"{k}={v}" for k, v in sorted(s["metric"].get("labels", {}).items())
                           if k in ("type", "op", "api_method"))
            for p in s.get("points", []):
                agg[(p["interval"]["endTime"][:10], lab)] += val(p)
        res[metric] = {f"{d} {l}": v for (d, l), v in sorted(agg.items())}
        tot = sum(agg.values())
        print(f"-- {metric}  (total {tot:,.0f})")
        for (d, l), v in sorted(agg.items()):
            if v:
                print(f"   {d}  {l:40} {v:>12,.0f}")

    # Heures d'instance par version : moyenne du nombre d'instances par minute.
    ts = series("appengine.googleapis.com/system/instance_count", "ALIGN_MEAN", 60)
    hours = defaultdict(float)
    for s in ts:
        v = s["resource"]["labels"].get("version_id", "?")
        st = s["metric"].get("labels", {}).get("state", "")
        for p in s.get("points", []):
            hours[(v, st)] += val(p) / 60.0
    res["instance_hours"] = {f"{v} {st}": round(h, 2) for (v, st), h in sorted(hours.items())}
    print("-- appengine.googleapis.com/system/instance_count -> heures d'instance")
    for (v, st), h in sorted(hours.items()):
        print(f"   {v:18} {st:10} {h:8.2f} h")
    save("usage.json", res)


# ----------------------------------------------------------------------- G
@guarded
def prices():
    section("G. Grille tarifaire officielle (Cloud Billing Catalog API)")
    loc = sh("gcloud", "firestore", "databases", "describe", "--database=(default)",
             "--format=value(locationId)")
    region = sh("gcloud", "app", "describe", "--format=value(locationId)")
    region = {"europe-west": "europe-west1", "us-central": "us-central1"}.get(region, region)
    svcs = api("https://cloudbilling.googleapis.com/v1/services?pageSize=5000")["services"]
    want = {"Cloud Datastore", "Cloud Firestore", "App Engine"}
    keep = []
    for s in (s for s in svcs if s["displayName"] in want):
        tok, skus = None, []
        while True:
            url = (f"https://cloudbilling.googleapis.com/v1/{s['name']}/skus"
                   f"?pageSize=5000&currencyCode=USD" + (f"&pageToken={tok}" if tok else ""))
            r = api(url); skus += r.get("skus", []); tok = r.get("nextPageToken")
            if not tok:
                break
        for k in skus:
            regs = k.get("serviceRegions", [])
            if not ({loc, region, "global"} & set(regs)):
                continue
            d = k["description"]
            if not any(w in d for w in ("Read", "Write", "Delete", "Entit", "Stored",
                                        "Instance", "Backend", "Frontend")):
                continue
            pe = k["pricingInfo"][0]["pricingExpression"]
            tiers = [(t["startUsageAmount"],
                      int(t["unitPrice"].get("units", 0)) + t["unitPrice"].get("nanos", 0) / 1e9)
                     for t in pe["tieredRates"]]
            keep.append(dict(service=s["displayName"], sku=d, regions=regs,
                             unit=pe["usageUnitDescription"],
                             display_qty=pe.get("displayQuantity"), tiers=tiers))
    save("prices.json", keep)
    print(f"(base : {loc} ; App Engine : {region})")
    for k in keep:
        t = "  |  ".join(f"dès {a:g} : {p:.6g} $" for a, p in k["tiers"])
        print(f"{k['service'][:15]:15} {k['sku'][:62]:62} [{k['unit']}]  {t}")


if __name__ == "__main__":
    print(f"projet {PROJECT}   relevé {NOW}")
    for step in (platform, code_path, version_events, gunicorn, pending, usage, prices):
        step()
    print(f"\nPreuves brutes écrites dans {OUT}/")
