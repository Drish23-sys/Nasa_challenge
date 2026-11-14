#!/usr/bin/env python3
"""Generate presentation-ready figures from data/sites.json into docs/figures/.

  python backend/scripts/make_figures.py            (adds a PLACEHOLDER watermark while data is mock/placeholder)
  python backend/scripts/make_figures.py --final    (no watermark, use once your real data is in)

Colors follow one validated palette: single-hue blue ramp for magnitude (heatmap), categorical
blue / orange / aqua for the three best analogs, dark ink for the target. Every chart is labelled
directly so meaning never depends on color alone.
"""
import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import scoring  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e3e2de"
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # categorical slots 1-3 (validated all-pairs)
CMAP = LinearSegmentedColormap.from_list("blue_seq", BLUE_RAMP)
FACTOR_LABEL = {"slope": "Slope", "roughness": "Roughness", "temp_range": "Temp extremes",
                "aridity": "Aridity", "basaltic": "Basaltic"}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "text.color": INK, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.edgecolor": GRID, "font.size": 10, "axes.titleweight": "bold", "axes.titlesize": 12,
})


def watermark(fig, on):
    if on:
        fig.text(0.5, 0.5, "PLACEHOLDER DATA", ha="center", va="center", fontsize=44, color="#0b0b0b",
                 alpha=0.07, rotation=22, weight="bold")


def short(name):
    return name.split(",")[0]


def heatmap(data, wm, out):
    cands = data["candidates"]
    M = np.array([[scoring.score_pair(t["factors"], c["factors"])["score"] for c in cands] for t in data["targets"]])
    order = np.argsort(-M.mean(axis=0))
    M, names = M[:, order], [short(cands[i]["name"]) for i in order]
    fig, ax = plt.subplots(figsize=(15, 3.8))
    im = ax.imshow(M, cmap=CMAP, vmin=0.4, vmax=1.0, aspect="auto")
    ax.set_xticks(range(len(names)), names, rotation=40, ha="right")
    ax.set_yticks(range(len(data["targets"])), [t["name"] for t in data["targets"]])
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            v = M[i, j]
            ax.text(j, i, f"{round(v * 100)}", ha="center", va="center", fontsize=8,
                    color="white" if (v - 0.4) / 0.6 > 0.5 else INK)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("How closely each Earth site matches each Moon / Mars target (similarity %, equal weights)", loc="left")
    cb = fig.colorbar(im, ax=ax, fraction=0.012, pad=0.01)
    cb.set_label("similarity", color=INK2)
    watermark(fig, wm)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def ranking(data, wm, out, top=8):
    fig, axes = plt.subplots(2, 2, figsize=(13, 7.2))
    for ax, t in zip(axes.ravel(), data["targets"]):
        r = scoring.rank(t, data["candidates"], top_n=top)[::-1]
        y = np.arange(len(r))
        ax.barh(y, [x["score"] * 100 for x in r], color=SERIES[0], height=0.62)
        for yi, x in zip(y, r):
            ax.text(x["score"] * 100 + 0.8, yi, f"{round(x['score'] * 100)}%", va="center", fontsize=9, color=INK)
        ax.set_yticks(y, [short(x["name"]) for x in r])
        ax.set_xlim(0, 108)
        ax.xaxis.grid(True, color=GRID)
        ax.set_axisbelow(True)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.tick_params(left=False)
        ax.set_title(f"{t['name']} ({t['body']})", loc="left")
    fig.suptitle(f"Top {top} Earth analogs per target (similarity %, equal weights)", x=0.01, ha="left", fontweight="bold")
    watermark(fig, wm)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def radar(data, wm, out):
    facs = list(scoring.FACTORS)
    ang = np.linspace(0, 2 * np.pi, len(facs), endpoint=False)
    ang = np.r_[ang, ang[0]]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 9.2), subplot_kw={"polar": True})
    for ax, t in zip(axes.ravel(), data["targets"]):
        top = scoring.rank(t, data["candidates"], top_n=3)
        cand = {c["id"]: c for c in data["candidates"]}
        vals = [t["factors"][f] for f in facs]
        ax.plot(ang, vals + vals[:1], color=INK, lw=2.4, ls="--", label=f"TARGET: {short(t['name'])}")
        for col, r in zip(SERIES, top):
            v = [cand[r["id"]]["factors"][f] for f in facs]
            ax.plot(ang, v + v[:1], color=col, lw=2, label=f"#{r['rank']} {short(r['name'])} ({round(r['score'] * 100)}%)")
        ax.set_ylim(0, 1)
        ax.set_yticks([0.25, 0.5, 0.75], ["", "", ""])
        ax.set_xticks(ang[:-1], [FACTOR_LABEL[f] for f in facs], fontsize=9)
        ax.grid(color=GRID)
        ax.spines["polar"].set_color(GRID)
        ax.set_title(t["name"], pad=16, loc="center")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), fontsize=8, frameon=False)
    fig.suptitle("Factor profile: each target vs its three best Earth analogs (0-1, higher = more of it)", x=0.01, ha="left", fontweight="bold")
    watermark(fig, wm)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true", help="omit the placeholder watermark")
    a = ap.parse_args()
    data = json.loads((ROOT / "data" / "sites.json").read_text())
    version = (data["meta"].get("version") or "").lower()
    wm = not a.final and ("mock" in version or "placeholder" in version)
    out = ROOT / "docs" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    heatmap(data, wm, out / "similarity_heatmap.png")
    ranking(data, wm, out / "ranking_top8.png")
    radar(data, wm, out / "factor_profiles.png")
    print("wrote 3 figures to", out, "(watermarked)" if wm else "")


if __name__ == "__main__":
    main()
