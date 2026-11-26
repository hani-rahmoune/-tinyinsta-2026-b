#!/usr/bin/env python3
"""Regenere toutes les figures et tous les CSV a partir de raw/.

    make figures    (ou python scripts/analyze.py)

Fichiers lus : raw/p1_u_<U>.csv, raw/p1_p_<P>.csv, raw/p1_f_<F>.csv,
raw/p2_n<N>_c<C>.csv, raw/p3_n<N>_c<C>.csv, et raw/verify/ (bench/verify.py).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

LIMIT = 20

#limite du IN mesuree par bench/verify.py (raw/verify/in_limit.json)

IN_LIMIT = 30
CLIFF_F = IN_LIMIT

DATASETS = {"u100": (100, 20, 20), "base": (1000, 20, 20), "u10k": (10000, 20, 20),
            "p10": (100, 10, 20), "p100": (100, 100, 20), "p1000": (100, 1000, 20),
            **{f"f{f:02d}": (120, 20, f) for f in range(5, 101, 5)}}


COL = {1: "#1f4e79", 2: "#c1121f", 4: "#2a9d8f", 8: "#9d4edd"}


def reads_per_timeline(P: int, F: int, limit: int = LIMIT) -> tuple[int, str]:
    # 1 lecture du User, puis un seul IN si F+1 <= 30, sinon une requete par auteur
    authors = F + 1
    if authors <= IN_LIMIT:
        return 1 + min(limit, authors * P), "IN (main.py:61-64)"
    return 1 + authors * min(limit, P), "repli par auteur (main.py:66-72)"


def load_run(path: str, warmup: float) -> dict | None:
    try:
        df = pd.read_csv(path)
    except Exception as e:  # noqa: BLE001
        print(f"  ! {path}: illisible ({e})", file=sys.stderr)
        return None
    if df.empty:
        print(f"  ! {path}: vide", file=sys.stderr)
        return None

    for c in ("T_START", "LATENCY_MS", "SERVER_MS", "STATUS", "USERS"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    df = df.dropna(subset=["T_START"])

    t0 = df["T_START"].min()
    kept = df[df["T_START"] >= t0 + warmup]
    if len(kept) < 5:
        kept = df


    codes_all = df["STATUS"].fillna(0).astype(int).value_counts().sort_index()
    errs_all = df["ERROR"].dropna().astype(str)
    errs_all = errs_all[errs_all.str.strip() != ""].value_counts().sort_index()
    ok = kept[kept["STATUS"] == 200]
    span = kept["T_START"].max() - kept["T_START"].min()
    codes = kept["STATUS"].fillna(0).astype(int).value_counts().sort_index()
    inst = sorted(x for x in kept["INSTANCE"].dropna().unique() if str(x).strip())

    return {
        "file": os.path.basename(path),
        "n_rows_all": len(df),
        "http_codes_all": "|".join(f"{k}:{v}" for k, v in codes_all.items()),
        "client_errors_all": "|".join(f"{k}:{v}" for k, v in errs_all.items()),
        "n_total": len(kept),
        "n_ok": len(ok),
        "n_fail": int((kept["STATUS"] != 200).sum()),
        "http_codes": "|".join(f"{k}:{v}" for k, v in codes.items()),
        "instances_observed": len(inst),
        "instance_ids": " ".join(str(i)[:12] for i in inst),
        "users_observed_max": int(kept["USERS"].max()) if kept["USERS"].notna().any() else 0,
        "client_ms_median": float(ok["LATENCY_MS"].median()) if len(ok) else np.nan,
        "client_ms_mean": float(ok["LATENCY_MS"].mean()) if len(ok) else np.nan,
        "client_ms_p95": float(ok["LATENCY_MS"].quantile(0.95)) if len(ok) else np.nan,
        "server_ms_median": float(ok["SERVER_MS"].median()) if ok["SERVER_MS"].notna().any() else np.nan,
        "server_ms_p95": float(ok["SERVER_MS"].quantile(0.95)) if ok["SERVER_MS"].notna().any() else np.nan,
        "throughput_rps": len(ok) / span if span > 0 else np.nan,
        "window_s": float(span),
    }


def collect(raw: str, pattern: str, warmup: float) -> list[dict]:
    rx = re.compile(pattern)
    rows = []
    for path in sorted(glob.glob(os.path.join(raw, "*.csv"))):
        m = rx.match(os.path.basename(path))
        if not m:
            continue
        st = load_run(path, warmup)
        if st:
            rows.append({**{k: int(v) for k, v in m.groupdict().items()}, **st})
    return rows


def pool(rows: list[dict], keys: list[str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    num = ["client_ms_median", "client_ms_mean", "client_ms_p95", "server_ms_median", "server_ms_p95",
           "throughput_rps", "window_s"]
    agg = {c: "mean" for c in num}
    agg.update({"n_ok": "sum", "n_fail": "sum", "n_total": "sum",
                "instances_observed": "max", "users_observed_max": "max",
                "http_codes": lambda s: "|".join(sorted(set(s))),
                "file": lambda s: " ".join(sorted(s))})
    return df.groupby(keys, as_index=False).agg(agg).sort_values(keys)


def save(df: pd.DataFrame, fig, name: str, out: str) -> None:
    df.to_csv(os.path.join(out, f"{name}.csv"), index=False)
    fig.savefig(os.path.join(out, f"{name}.png"), dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {out}/{name}.csv + {name}.png ({len(df)} points)")


def style(ax, xlabel, ylabel, title, sub=None):
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title if sub is None else f"{title}\n{sub}", fontsize=10)
    ax.grid(alpha=.3, linewidth=.6)
    ax.spines[["top", "right"]].set_visible(False)


def fig1a(raw, out, warmup):
    u = pool(collect(raw, r"p1_u_(?P<U>\d+)(_r\d+)?\.csv$", warmup), ["U"])
    p = pool(collect(raw, r"p1_p_(?P<P>\d+)(_r\d+)?\.csv$", warmup), ["P"])
    if u.empty and p.empty:
        print("  ! fig1a: aucun run p1_u_* / p1_p_*", file=sys.stderr)
        return pd.DataFrame()

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    top = 1.0
    for ax, df, key, lab, fixed in (
        (axes[0], u, "U", "utilisateurs dans le jeu (U)", "P=20, F=20"),
        (axes[1], p, "P", "posts par utilisateur (P)", "U=100, F=20"),
    ):
        if df.empty:
            continue
        ax.plot(df[key], df["server_ms_median"], "o-", color=COL[1], lw=1.8, ms=6)
        ax.set_xscale("log")
        style(ax, lab, "temps serveur médian (ms)",
              f"Fig. 1a : temps serveur selon {key}",
              f"fixed1, 1 requête à la fois ({fixed}, limit=20), runs de 45 s")
        top = max(top, float(df["server_ms_median"].max()))
    # axe y a partir de 0, sinon une courbe plate a l'air de bouger
    for ax in axes:
        ax.set_ylim(0, top * 1.35)
    fig.tight_layout()

    tidy = pd.concat([
        u.assign(factor="U", factor_value=u["U"]) if not u.empty else pd.DataFrame(),
        p.assign(factor="P", factor_value=p["P"]) if not p.empty else pd.DataFrame(),
    ], ignore_index=True)
    cols = ["factor", "factor_value", "server_ms_median", "server_ms_p95",
            "client_ms_median", "client_ms_p95", "throughput_rps",
            "n_ok", "n_fail", "instances_observed", "http_codes", "file"]
    tidy = tidy[[c for c in cols if c in tidy]]
    save(tidy, fig, "fig1a", out)
    return tidy


def fig1b(raw, out, warmup):
    f = pool(collect(raw, r"p1_f_(?P<F>\d+)(_r\d+)?\.csv$", warmup), ["F"])
    if f.empty:
        print("  ! fig1b: aucun run p1_f_*", file=sys.stderr)
        return f
    f["client_minus_server_ms"] = f["client_ms_median"] - f["server_ms_median"]
    f["entity_reads_per_timeline"] = [reads_per_timeline(20, int(x))[0] for x in f["F"]]

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ax.plot(f["F"], f["client_ms_median"], "s-", color=COL[2], lw=1.6, ms=5,
            label="latence client (médiane)")
    ax.plot(f["F"], f["server_ms_median"], "o-", color=COL[1], lw=1.8, ms=5,
            label="temps serveur (médian)")

    # pente du temps serveur, une par regime (citee dans le README)
    ok = f.dropna(subset=["server_ms_median"])
    for lab, seg in ((f"F < {CLIFF_F}", ok[ok["F"] < CLIFF_F]), (f"F >= {CLIFF_F}", ok[ok["F"] >= CLIFF_F])):
        if len(seg) >= 3:
            a, _ = np.polyfit(seg["F"], seg["server_ms_median"], 1)
            print(f"  pente {lab} : {a:.2f} ms/followee")
    style(ax, "followees par utilisateur (F)", "temps (ms)",
          "Fig. 1b : coût d'une timeline selon F",
          "fixed1, 1 requête à la fois (U=120, P=20, limit=20), runs de 45 s")
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()

    cols = ["F", "server_ms_median", "server_ms_p95", "client_ms_median",
            "client_ms_p95", "client_minus_server_ms", "entity_reads_per_timeline",
            "n_ok", "n_fail", "instances_observed", "http_codes", "file"]
    save(f[[c for c in cols if c in f]], fig, "fig1b", out)
    return f


def part2(raw, out, warmup, tag="p2"):
    d = pool(collect(raw, rf"{tag}_n(?P<N>\d+)_c(?P<C>\d+)(_r\d+)?\.csv$", warmup),
             ["N", "C"])
    if d.empty:
        return d
    # Little relie C a la latence MOYENNE
    d["little_latency_ms"] = 1000 * d["C"] / d["throughput_rps"]
    d["little_vs_mean_pct"] = 100 * (d["little_latency_ms"] / d["client_ms_mean"] - 1)
    d["little_vs_median_pct"] = 100 * (d["little_latency_ms"] / d["client_ms_median"] - 1)
    return d


def log2_c(ax, d):
    ax.set_xscale("log", base=2)
    ax.set_xticks(sorted(d["C"].unique()))
    ax.get_xaxis().set_major_formatter(mticker.ScalarFormatter())


def fig2(d, out):
    if d.empty:
        print("  ! fig2: aucun run p2_*", file=sys.stderr)
        return
    cols = ["N", "C", "throughput_rps", "client_ms_median", "client_ms_mean", "client_ms_p95",
            "server_ms_median", "little_latency_ms", "little_vs_mean_pct",
            "little_vs_median_pct", "instances_observed",
            "users_observed_max", "n_ok", "n_fail", "http_codes", "window_s", "file"]
    cols = [c for c in cols if c in d]
    sub = "fixed1/fixed2/fixed4 (B1), jeu base (U=1000, P=20, F=20, limit=20), runs de 75 s"

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for n, g in d.groupby("N"):
        ax.plot(g["C"], g["throughput_rps"], "o-", lw=1.8, ms=5,
                color=COL.get(n, "#444"), label=f"N = {n} instance(s)")
    log2_c(ax, d)
    style(ax, "utilisateurs Locust simultanés (C)", "débit (requêtes/s)",
          "Fig. 2a : débit selon la concurrence", sub)
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    save(d[cols], fig, "fig2a", out)

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for n, g in d.groupby("N"):
        c = COL.get(n, "#444")
        ax.plot(g["C"], g["client_ms_median"], "o-", lw=1.8, ms=5, color=c,
                label=f"N = {n}, médiane mesurée")
        ax.plot(g["C"], g["little_latency_ms"], "--", lw=1.2, color=c, alpha=.75,
                label=f"N = {n}, Little (C / débit)")
    log2_c(ax, d)
    ax.set_yscale("log")
    style(ax, "utilisateurs Locust simultanés (C)", "latence client (ms)",
          "Fig. 2b : latence selon la concurrence, et loi de Little", sub)
    ax.legend(frameon=False, fontsize=8, ncol=3)
    fig.tight_layout()
    save(d[cols], fig, "fig2b", out)


def fig3(before, after, out):
    if before.empty or after.empty:
        print("  ! fig3: il faut p2_n1_* (avant) et p3_n1_* (apres)", file=sys.stderr)
        return
    b = before[before["N"] == 1].assign(variant="before (1 sync worker)")
    a = after[after["N"] == 1].assign(variant="after (2 workers x 8 threads)")
    if b.empty or a.empty:
        print("  ! fig3: serie N=1 manquante", file=sys.stderr)
        return
    d = pd.concat([b, a], ignore_index=True)

    labels = {"before (1 sync worker)": "avant (1 worker sync)",
              "after (2 workers x 8 threads)": "après (2 workers x 8 threads)"}
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for g, c, m in ((b, COL[1], "o-"), (a, COL[2], "s-")):
        lab = labels[g["variant"].iloc[0]]
        axes[0].plot(g["C"], g["throughput_rps"], m, color=c, lw=1.8, ms=5, label=lab)
        axes[1].plot(g["C"], g["client_ms_median"], m, color=c, lw=1.8, ms=5, label=lab)
    for ax, yl, t in ((axes[0], "débit (requêtes/s)", "débit"),
                      (axes[1], "latence client médiane (ms)", "latence")):
        log2_c(ax, d)
        style(ax, "utilisateurs Locust simultanés (C)", yl, f"Fig. 3 : {t}, avant / après",
              "N=1 (fixed1 vs fix1, B1), runs de 75 s" + chr(10) + "jeu base (U=1000, P=20, F=20, limit=20)")
        ax.set_ylim(bottom=0)
        ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()

    cols = ["variant", "N", "C", "throughput_rps", "client_ms_median",
            "server_ms_median", "little_latency_ms", "n_ok", "n_fail",
            "instances_observed", "http_codes", "file"]
    save(d[[c for c in cols if c in d]], fig, "fig3", out)


def _price(prices, sku):
    # prix au-dela de la franchise, et taille de la franchise
    for k in prices:
        if k["service"] == "App Engine" and k["sku"] == sku:
            tiers = sorted(k["tiers"])
            free = tiers[1][0] if len(tiers) > 1 and tiers[0][1] == 0 else 0
            return tiers[-1][1], free, k["unit"]
    raise KeyError(sku)


def costs(raw, out):
    vdir = os.path.join(raw, "verify")
    try:
        prices = json.load(open(os.path.join(vdir, "prices.json")))
        usage = json.load(open(os.path.join(vdir, "usage.json")))
        measured = pd.read_csv(os.path.join(vdir, "reads_per_timeline.csv"))
    except OSError as e:
        print(f"  ! couts: lancer bench/verify.py d'abord ({e})", file=sys.stderr)
        return
    # les SKU Datastore sont ranges sous le service App Engine dans le catalogue
    read_usd, read_free, _ = _price(prices, "Cloud Datastore Read Ops")

    rows = []
    for prefix, (U, P, F) in DATASETS.items():
        reads, path = reads_per_timeline(P, F)
        m = measured[measured["prefix"] == prefix]
        rows.append({"dataset": prefix, "U": U, "P": P, "F": F, "authors": F + 1,
                     "path": path, "entity_reads_per_timeline": reads,
                     "entity_reads_measured": int(m["entities_read"].iloc[0]) if len(m) else "",
                     "entity_reads_per_1M_timelines": reads * 1_000_000,
                     "usd_per_read_catalogue": read_usd,
                     "usd_per_1M_timelines": round(reads * 1_000_000 * read_usd, 2)})
    df = pd.DataFrame(rows)
    chk = df[df["entity_reads_measured"] != ""]
    bad = chk[chk["entity_reads_measured"].astype(int) != chk["entity_reads_per_timeline"]]
    if len(bad):
        print(f"  ! le modele contredit la mesure pour {list(bad['dataset'])}", file=sys.stderr)
    df.to_csv(os.path.join(out, "cost_1M_timelines.csv"), index=False)
    print(f"  -> {out}/cost_1M_timelines.csv (modele verifie sur {len(chk)} jeux, "
          f"{len(bad)} ecart)")

    def total(metric, pred=lambda k: True):
        return sum(v for k, v in usage.get(metric, {}).items() if pred(k))
    rd = "datastore.googleapis.com/entity/read_sizes"
    wr = "datastore.googleapis.com/entity/write_sizes"
    hours = defaultdict(float)
    for k, v in usage.get("instance_hours", {}).items():
        hours[k.split(" ")[0]] += v
    lines = [
        ("entity reads (lookup)", total(rd, lambda k: "ENTITY_FETCH" in k), "count"),
        ("entity reads (query)", total(rd, lambda k: "ENTITY_SCAN" in k), "count"),
        ("entity reads (keys-only query)", total(rd, lambda k: "KEYS_ONLY" in k), "count"),
        ("entity writes (create)", total(wr, lambda k: "CREATE" in k), "count"),
        ("entity deletes", total(wr, lambda k: "DELETE" in k), "count"),
    ]
    for v, h in sorted(hours.items()):
        cls = "B1" if v.startswith("fix") else "F1"
        lines.append((f"instance-hours {v} ({cls})", round(h, 2), "hour"))
    camp = pd.DataFrame(lines, columns=["item", "quantity", "unit"])
    camp.to_csv(os.path.join(out, "campaign_cost.csv"), index=False)
    print(f"  -> {out}/campaign_cost.csv ({len(camp)} postes)")


def summary(raw, out, warmup):
    rows = [load_run(p, warmup) for p in sorted(glob.glob(os.path.join(raw, "*.csv")))]
    rows = [r for r in rows if r]
    if not rows:
        print("  ! summary: raw/ est vide", file=sys.stderr)
        return
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "summary.csv"), index=False)
    print(f"  -> {out}/summary.csv ({len(df)} runs)")
    bad = df[df["n_fail"] > 0]
    if len(bad):
        print(f"\n  {len(bad)} run(s) avec des reponses non 200 :")
        for _, r in bad.iterrows():
            print(f"    {r['file']}: {r['n_fail']}/{r['n_total']} en echec [{r['http_codes']}]")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--out", default="figures")
    ap.add_argument("--warmup", type=float, default=10.0,
                    help="secondes ecartees au debut de chaque run (10 par defaut)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    print(f"raw = {a.raw}/  out = {a.out}/  warmup = {a.warmup}s")
    print("\nPartie 1")
    fig1a(a.raw, a.out, a.warmup)
    fig1b(a.raw, a.out, a.warmup)
    print("\nPartie 2")
    p2 = part2(a.raw, a.out, a.warmup, "p2")
    fig2(p2, a.out)
    print("\nPartie 3")
    fig3(p2, part2(a.raw, a.out, a.warmup, "p3"), a.out)
    print("\nCouts et resume")
    costs(a.raw, a.out)
    summary(a.raw, a.out, a.warmup)
    print("\nfini.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
