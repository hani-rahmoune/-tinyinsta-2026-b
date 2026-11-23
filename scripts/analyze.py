#!/usr/bin/env python3
"""TinyInsta 2026 — regenerate every figure and CSV from raw/ in one command.

    make figures          #  ==  python scripts/analyze.py

Reads raw/*.csv produced by bench/locustfile.py, whose names encode the
experiment:

    raw/p1_u_<U>.csv        Part 1, factor U   (P=20,  F=20)
    raw/p1_p_<P>.csv        Part 1, factor P   (U=100, F=20)
    raw/p1_f_<F>.csv        Part 1, factor F   (U=120, P=20)
    raw/p2_n<N>_c<C>.csv    Part 2, N fixed instances, concurrency C
    raw/p3_n<N>_c<C>.csv    Part 3, same protocol on the fixed version

An optional _r<k> suffix marks a repeat; repeats are pooled.

Writes figures/fig{1a,1b,2a,2b,3}.{csv,png} plus two extras used by the
report: figures/summary.csv (per-run diagnostics: instances actually seen,
HTTP codes, failures) and figures/cost_model.csv (Datastore read model).

Missing runs are skipped with a warning, so partial campaigns still plot.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# One request to /api/timeline?limit=20 reads, at worst, the User entity plus
# limit entities per author of the IN-expansion (F followees + the user itself).
LIMIT = 20
USD_PER_100K_READS = 0.06   # check the current Datastore grid and update here

COL = {1: "#1f4e79", 2: "#c1121f", 4: "#2a9d8f", 8: "#9d4edd"}


# ----------------------------------------------------------------- loading
def load_run(path: str, warmup: float) -> dict | None:
    """Per-run statistics, after dropping the first `warmup` seconds."""
    try:
        df = pd.read_csv(path)
    except Exception as e:                                    # noqa: BLE001
        print(f"  ! {path}: unreadable ({e})", file=sys.stderr)
        return None
    if df.empty:
        print(f"  ! {path}: empty", file=sys.stderr)
        return None

    for c in ("T_START", "LATENCY_MS", "SERVER_MS", "STATUS", "USERS"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    df = df.dropna(subset=["T_START"])

    t0 = df["T_START"].min()
    kept = df[df["T_START"] >= t0 + warmup]
    if len(kept) < 5:          # very short run: keep everything rather than nothing
        kept = df

    ok = kept[kept["STATUS"] == 200]
    span = kept["T_START"].max() - kept["T_START"].min()
    codes = kept["STATUS"].fillna(0).astype(int).value_counts().sort_index()
    inst = sorted(x for x in kept["INSTANCE"].dropna().unique() if str(x).strip())

    return {
        "file": os.path.basename(path),
        "n_total": len(kept),
        "n_ok": len(ok),
        "n_fail": int((kept["STATUS"] != 200).sum()),
        "http_codes": "|".join(f"{k}:{v}" for k, v in codes.items()),
        "instances_observed": len(inst),
        "instance_ids": " ".join(str(i)[:12] for i in inst),
        "users_observed_max": int(kept["USERS"].max()) if kept["USERS"].notna().any() else 0,
        "client_ms_median": float(ok["LATENCY_MS"].median()) if len(ok) else np.nan,
        "client_ms_p95": float(ok["LATENCY_MS"].quantile(0.95)) if len(ok) else np.nan,
        "server_ms_median": float(ok["SERVER_MS"].median()) if ok["SERVER_MS"].notna().any() else np.nan,
        "server_ms_p95": float(ok["SERVER_MS"].quantile(0.95)) if ok["SERVER_MS"].notna().any() else np.nan,
        "throughput_rps": len(ok) / span if span > 0 else np.nan,
        "window_s": float(span),
    }


def collect(raw: str, pattern: str, warmup: float) -> list[dict]:
    """All runs whose basename matches `pattern`; named groups become columns."""
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
    """Average repeats of the same experimental point."""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    num = ["client_ms_median", "client_ms_p95", "server_ms_median", "server_ms_p95",
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
    print(f"  -> {out}/{name}.csv  +  {name}.png   ({len(df)} points)")


def style(ax, xlabel, ylabel, title, sub=None):
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title if sub is None else f"{title}\n{sub}", fontsize=10)
    ax.grid(alpha=.3, linewidth=.6)
    ax.spines[["top", "right"]].set_visible(False)


# -------------------------------------------------------------- figure 1a
def fig1a(raw, out, warmup):
    u = pool(collect(raw, r"p1_u_(?P<U>\d+)(_r\d+)?\.csv$", warmup), ["U"])
    p = pool(collect(raw, r"p1_p_(?P<P>\d+)(_r\d+)?\.csv$", warmup), ["P"])

    # p1_u_100 is U=100, P=20, F=20 -> it is also the P=20 point of the P series.
    if not u.empty and 100 in set(u["U"]) and not p.empty:
        row = u[u["U"] == 100].iloc[0].to_dict()
        row["P"] = 20
        p = pd.concat([p, pd.DataFrame([row]).drop(columns=["U"])],
                      ignore_index=True).sort_values("P")

    if u.empty and p.empty:
        print("  ! fig1a: no p1_u_* / p1_p_* runs", file=sys.stderr)
        return pd.DataFrame()

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    top = 1.0
    for ax, df, key, lab, fixed in (
        (axes[0], u, "U", "users in the dataset (U)", "P=20, F=20"),
        (axes[1], p, "P", "posts per user (P)", "U=100, F=20"),
    ):
        if df.empty:
            continue
        ax.plot(df[key], df["server_ms_median"], "o-", color=COL[1], lw=1.8, ms=6)
        ax.set_xscale("log")
        style(ax, lab, "median server time (ms)",
              f"Fig. 1a — server time vs {key}",
              f"fixed1, 1 request at a time ({fixed})")
        top = max(top, float(df["server_ms_median"].max()))
    for ax in axes:                     # 0-based y: a flat line must LOOK flat
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


# -------------------------------------------------------------- figure 1b
def fig1b(raw, out, warmup):
    f = pool(collect(raw, r"p1_f_(?P<F>\d+)(_r\d+)?\.csv$", warmup), ["F"])
    if f.empty:
        print("  ! fig1b: no p1_f_* runs", file=sys.stderr)
        return f
    f["network_ms_median"] = f["client_ms_median"] - f["server_ms_median"]
    f["entity_reads_upper_bound"] = 1 + (f["F"] + 1) * LIMIT

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ax.plot(f["F"], f["client_ms_median"], "s-", color=COL[2], lw=1.6, ms=5,
            label="client latency (median)")
    ax.plot(f["F"], f["server_ms_median"], "o-", color=COL[1], lw=1.8, ms=5,
            label="server time (median)")

    ok = f.dropna(subset=["server_ms_median"])
    if len(ok) >= 3:                      # linearity is the claim -> show the fit
        a, b = np.polyfit(ok["F"], ok["server_ms_median"], 1)
        xs = np.linspace(ok["F"].min(), ok["F"].max(), 50)
        ax.plot(xs, a * xs + b, "--", color="#555", lw=1.2,
                label=f"linear fit: {a:.2f} ms per followee")
    style(ax, "followees per user (F)", "time (ms)",
          "Fig. 1b — timeline cost vs F",
          "fixed1, 1 request at a time (U=120, P=20, limit=20)")
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()

    cols = ["F", "server_ms_median", "server_ms_p95", "client_ms_median",
            "client_ms_p95", "network_ms_median", "entity_reads_upper_bound",
            "n_ok", "n_fail", "instances_observed", "http_codes", "file"]
    save(f[[c for c in cols if c in f]], fig, "fig1b", out)
    return f


# --------------------------------------------------------- figures 2a / 2b
def part2(raw, out, warmup, tag="p2"):
    d = pool(collect(raw, rf"{tag}_n(?P<N>\d+)_c(?P<C>\d+)(_r\d+)?\.csv$", warmup),
             ["N", "C"])
    if d.empty:
        return d
    d["little_latency_ms"] = 1000 * d["C"] / d["throughput_rps"]
    return d


def fig2(d, out):
    if d.empty:
        print("  ! fig2: no p2_* runs", file=sys.stderr)
        return
    cols = ["N", "C", "throughput_rps", "client_ms_median", "client_ms_p95",
            "server_ms_median", "little_latency_ms", "instances_observed",
            "users_observed_max", "n_ok", "n_fail", "http_codes", "window_s", "file"]
    cols = [c for c in cols if c in d]

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for n, g in d.groupby("N"):
        ax.plot(g["C"], g["throughput_rps"], "o-", lw=1.8, ms=5,
                color=COL.get(n, "#444"), label=f"N = {n} instance(s)")
    ax.set_xscale("log", base=2)
    ax.set_xticks(sorted(d["C"].unique()))
    ax.get_xaxis().set_major_formatter(mticker.ScalarFormatter())
    style(ax, "concurrent Locust users (C)", "throughput (requests/s)",
          "Fig. 2a — throughput vs concurrency", "dataset base (U=1000, P=20, F=20)")
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    save(d[cols], fig, "fig2a", out)

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for n, g in d.groupby("N"):
        c = COL.get(n, "#444")
        ax.plot(g["C"], g["client_ms_median"], "o-", lw=1.8, ms=5, color=c,
                label=f"N = {n}, measured")
        ax.plot(g["C"], g["little_latency_ms"], "--", lw=1.2, color=c, alpha=.75,
                label=f"N = {n}, Little (C / throughput)")
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xticks(sorted(d["C"].unique()))
    ax.get_xaxis().set_major_formatter(mticker.ScalarFormatter())
    style(ax, "concurrent Locust users (C)", "median client latency (ms)",
          "Fig. 2b — latency vs concurrency, against Little's law",
          "dataset base (U=1000, P=20, F=20)")
    ax.legend(frameon=False, fontsize=8, ncol=2)
    fig.tight_layout()
    save(d[cols], fig, "fig2b", out)


# --------------------------------------------------------------- figure 3
def fig3(before, after, out):
    if before.empty or after.empty:
        print("  ! fig3: need both p2_n1_* (before) and p3_n1_* (after)", file=sys.stderr)
        return
    b = before[before["N"] == 1].assign(variant="before (1 sync worker)")
    a = after[after["N"] == 1].assign(variant="after (2 workers x 8 threads)")
    if b.empty or a.empty:
        print("  ! fig3: missing the N=1 series", file=sys.stderr)
        return
    d = pd.concat([b, a], ignore_index=True)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for g, c, m in ((b, COL[1], "o-"), (a, COL[2], "s-")):
        lab = g["variant"].iloc[0]
        axes[0].plot(g["C"], g["throughput_rps"], m, color=c, lw=1.8, ms=5, label=lab)
        axes[1].plot(g["C"], g["client_ms_median"], m, color=c, lw=1.8, ms=5, label=lab)
    for ax, yl, t in ((axes[0], "throughput (requests/s)", "throughput"),
                      (axes[1], "median client latency (ms)", "latency")):
        ax.set_xscale("log", base=2)
        ax.set_xticks(sorted(d["C"].unique()))
        ax.get_xaxis().set_major_formatter(mticker.ScalarFormatter())
        style(ax, "concurrent Locust users (C)", yl, f"Fig. 3 — {t}, before / after",
              "1 fixed instance, dataset base")
        ax.set_ylim(bottom=0)
        ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()

    cols = ["variant", "N", "C", "throughput_rps", "client_ms_median",
            "server_ms_median", "little_latency_ms", "n_ok", "n_fail",
            "instances_observed", "http_codes", "file"]
    save(d[[c for c in cols if c in d]], fig, "fig3", out)


# ------------------------------------------------------------------ extras
def cost_model(out):
    rows = []
    for f in list(range(5, 101, 5)) + [20]:
        reads = 1 + (f + 1) * LIMIT
        rows.append({
            "followees_F": f,
            "limit": LIMIT,
            "entity_reads_per_timeline_upper_bound": reads,
            "entity_reads_per_1M_timelines": reads * 1_000_000,
            "usd_per_100k_reads_assumed": USD_PER_100K_READS,
            "usd_per_1M_timelines": reads * 1_000_000 / 100_000 * USD_PER_100K_READS,
        })
    df = pd.DataFrame(rows).drop_duplicates("followees_F").sort_values("followees_F")
    df.to_csv(os.path.join(out, "cost_model.csv"), index=False)
    print(f"  -> {out}/cost_model.csv   (reads = 1 + (F+1)*limit, "
          f"at ${USD_PER_100K_READS}/100k)")


def summary(raw, out, warmup):
    rows = [load_run(p, warmup) for p in sorted(glob.glob(os.path.join(raw, "*.csv")))]
    rows = [r for r in rows if r]
    if not rows:
        print("  ! summary: raw/ is empty", file=sys.stderr)
        return
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "summary.csv"), index=False)
    print(f"  -> {out}/summary.csv   ({len(df)} runs)")
    bad = df[df["n_fail"] > 0]
    if len(bad):
        print(f"\n  ATTENTION: {len(bad)} run(s) with non-200 responses:")
        for _, r in bad.iterrows():
            print(f"    {r['file']}: {r['n_fail']}/{r['n_total']} failed  [{r['http_codes']}]")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--out", default="figures")
    ap.add_argument("--warmup", type=float, default=10.0,
                    help="seconds dropped at the start of every run (default 10)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    print(f"raw = {a.raw}/   out = {a.out}/   warmup = {a.warmup}s")
    print("\nPart 1")
    fig1a(a.raw, a.out, a.warmup)
    fig1b(a.raw, a.out, a.warmup)
    print("\nPart 2")
    p2 = part2(a.raw, a.out, a.warmup, "p2")
    fig2(p2, a.out)
    print("\nPart 3")
    fig3(p2, part2(a.raw, a.out, a.warmup, "p3"), a.out)
    print("\nExtras")
    cost_model(a.out)
    summary(a.raw, a.out, a.warmup)
    print("\ndone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
