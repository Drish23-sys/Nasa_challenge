#!/usr/bin/env python3
"""Build data/sites.json from real data.

What it does
------------
For each Earth candidate in sites_seed.json:
  * TERRAIN  - samples a small grid of elevations (default 5x5 points, 500 m apart) from the
               OpenTopoData API (free, no key; default dataset 'mapzen' has global coverage,
               SRTM stops at 60 N/S) and computes mean slope and roughness (residual std-dev
               after removing the best-fit plane).
  * CLIMATE  - NASA POWER climatology (free, no key): annual air-temperature extreme range
               (max monthly T2M_MAX minus min monthly T2M_MIN) and annual precipitation.
  * GEOLOGY  - 'basaltic' comes from sites_seed.json (hand-tagged, so confidence = estimated).

Targets (Moon/Mars) come from targets.json as RAW physical values and are normalized with the
SAME functions, so the comparison is consistent. Replace the placeholder values there with
numbers derived from LOLA/Diviner (Moon) or MOLA/THEMIS (Mars) and cite them in 'source'.
For a DEM you downloaded yourself (GeoTIFF), see terrain_from_raster.py.

Run:     python backend/pipeline/build_sites.py            (needs internet the first time)
Offline: python backend/pipeline/build_sites.py --offline  (uses backend/pipeline/cache/)
Output:  data/sites.json and frontend/data/sites.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import requests

PIPE = Path(__file__).resolve().parent
ROOT = PIPE.parents[1]
CACHE = PIPE / "cache"

TOPO_URL = "https://api.opentopodata.org/v1/{dataset}"
POWER_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"

GRID_N = 5
GRID_SPACING_M = 500.0

# Normalization constants. Change them here and re-run; targets use the same values.
NORM = {
    "slope_deg_max": 25.0,      # slope at or above this counts as 1.0
    "roughness_m_max": 150.0,    # roughness at or above this counts as 1.0
    "temp_range_K_max": 200.0,  # temperature range at or above this counts as 1.0
    "precip_mm_day_humid": 3.0,  # precipitation at or above this counts as 0 aridity (~1100 mm/yr)
}

FACTOR_META = {
    "slope": {"label": "Slope", "desc": "Mean slope over a ~2 km patch (0 = flat, 1 = 25 degrees or steeper)"},
    "roughness": {"label": "Roughness", "desc": "Elevation scatter after removing the average tilt (0 = smooth, 1 = 50 m or more)"},
    "temp_range": {"label": "Temperature extremes",
                   "desc": "Thermal range (1 = 120 K or more). Earth uses annual air-temperature extremes; Moon/Mars use surface temperature range - a proxy, not an exact match."},
    "aridity": {"label": "Aridity", "desc": "1 = no precipitation. Moon and Mars are set to 1 (no rain)."},
    "basaltic": {"label": "Volcanic/basaltic geology", "desc": "Hand-tagged share of basaltic or volcanic terrain (0-1)"},
}


def clip01(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def norm_slope(deg): return clip01(deg / NORM["slope_deg_max"])
def norm_rough(m): return clip01(m / NORM["roughness_m_max"])
def norm_temp(k): return clip01(k / NORM["temp_range_K_max"])
def norm_aridity(p): return clip01(1.0 - p / NORM["precip_mm_day_humid"])


# ------------------------------------------------------------------ terrain
def grid_points(lat: float, lon: float, n: int = GRID_N, spacing: float = GRID_SPACING_M):
    half = (n - 1) / 2
    dlat = spacing / 111_320.0
    dlon = spacing / (111_320.0 * max(math.cos(math.radians(lat)), 0.05))
    return [(lat + (i - half) * dlat, lon + (j - half) * dlon) for i in range(n) for j in range(n)]


def terrain_stats(z: np.ndarray, spacing: float) -> tuple[float, float]:
    """z is an n x n elevation grid in metres. Returns (mean slope in degrees, roughness in metres)."""
    gy, gx = np.gradient(z, spacing)
    slope = float(np.degrees(np.arctan(np.hypot(gx, gy))).mean())
    n = z.shape[0]
    yy, xx = np.mgrid[0:n, 0:n] * spacing
    A = np.c_[np.ones(z.size), xx.ravel(), yy.ravel()]
    coef, *_ = np.linalg.lstsq(A, z.ravel(), rcond=None)
    rough = float((z.ravel() - A @ coef).std())
    return slope, rough


def fetch_elevations(points, dataset: str, offline: bool, key: str) -> list[float]:
    path = CACHE / f"terrain_{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    if offline:
        raise RuntimeError(f"offline and no cache for {path.name}")
    elev: list[float] = []
    for i in range(0, len(points), 100):
        chunk = points[i:i + 100]
        locs = "|".join(f"{la:.6f},{lo:.6f}" for la, lo in chunk)
        for attempt in range(3):
            r = requests.get(TOPO_URL.format(dataset=dataset), params={"locations": locs}, timeout=60)
            if r.status_code == 200:
                break
            time.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(f"OpenTopoData HTTP {r.status_code}: {r.text[:200]}")
        elev += [res["elevation"] for res in r.json()["results"]]
        time.sleep(1.2)  # public API allows ~1 request per second
    if any(e is None for e in elev):
        raise RuntimeError("OpenTopoData returned no-data cells (try another --dataset)")
    path.write_text(json.dumps(elev))
    return elev


# ------------------------------------------------------------------ climate
def fetch_power(lat: float, lon: float, offline: bool, key: str) -> dict:
    path = CACHE / f"power_{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    if offline:
        raise RuntimeError(f"offline and no cache for {path.name}")
    params = {"parameters": "T2M_MAX,T2M_MIN,PRECTOTCORR", "community": "RE",
              "longitude": f"{lon:.4f}", "latitude": f"{lat:.4f}", "format": "JSON"}
    for attempt in range(3):
        r = requests.get(POWER_URL, params=params, timeout=90)
        if r.status_code == 200:
            break
        time.sleep(3 * (attempt + 1))
    else:
        raise RuntimeError(f"NASA POWER HTTP {r.status_code}: {r.text[:200]}")
    par = r.json()["properties"]["parameter"]
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    tmax = [par["T2M_MAX"][m] for m in months]
    tmin = [par["T2M_MIN"][m] for m in months]
    if any(v is None or v <= -900 for v in tmax + tmin):
        raise RuntimeError("NASA POWER returned fill values for temperature")
    precip = par["PRECTOTCORR"]["ANN"]
    if precip is None or precip <= -900:
        raise RuntimeError("NASA POWER returned a fill value for precipitation")
    out = {"temp_range_K": float(max(tmax) - min(tmin)), "precip_mm_day": float(precip)}
    path.write_text(json.dumps(out))
    return out


# ------------------------------------------------------------------ build
def build(args) -> dict:
    CACHE.mkdir(exist_ok=True)
    seed = json.loads((PIPE / "sites_seed.json").read_text())
    targets_raw = json.loads((PIPE / "targets.json").read_text())

    previous = {}
    prev_path = ROOT / "data" / "sites.json"
    if prev_path.exists():
        previous = {c["id"]: c for c in json.loads(prev_path.read_text()).get("candidates", [])}

    candidates, problems = [], []
    for s in seed:
        key = f"{s['id']}_{args.dataset}_{GRID_N}x{GRID_SPACING_M:.0f}"
        pkey = f"{s['id']}"
        try:
            pts = grid_points(s["lat"], s["lon"])
            elev = np.array(fetch_elevations(pts, args.dataset, args.offline, key)).reshape(GRID_N, GRID_N)
            slope_deg, rough_m = terrain_stats(elev, GRID_SPACING_M)
            clim = fetch_power(s["lat"], s["lon"], args.offline, pkey)
            factors = {
                "slope": norm_slope(slope_deg), "roughness": norm_rough(rough_m),
                "temp_range": norm_temp(clim["temp_range_K"]), "aridity": norm_aridity(clim["precip_mm_day"]),
                "basaltic": s["basaltic"],
            }
            confidence = {f: "measured" for f in factors}
            confidence["basaltic"] = "estimated"
            raw = {"slope_deg": round(slope_deg, 2), "roughness_m": round(rough_m, 2),
                   "temp_range_K": round(clim["temp_range_K"], 1), "precip_mm_day": round(clim["precip_mm_day"], 3),
                   "mean_elevation_m": round(float(elev.mean()), 1)}
            provenance = {
                "slope": f"OpenTopoData '{args.dataset}', {GRID_N}x{GRID_N} grid at {GRID_SPACING_M:.0f} m",
                "roughness": f"OpenTopoData '{args.dataset}', plane-fit residual std-dev",
                "temp_range": "NASA POWER climatology, T2M_MAX / T2M_MIN monthly",
                "aridity": "NASA POWER climatology, PRECTOTCORR annual",
                "basaltic": "hand-tagged from published geology (replace with a geology layer if time allows)",
            }
        except Exception as exc:  # keep the previous values so the app still works
            problems.append((s["id"], str(exc)))
            old = previous.get(s["id"])
            if not old:
                raise
            factors, confidence = old["factors"], {f: "estimated" for f in old["factors"]}
            raw, provenance = old.get("raw", {}), {f: "fallback: previous/placeholder value" for f in old["factors"]}
        candidates.append({
            "id": s["id"], "name": s["name"], "type": s["type"], "lat": s["lat"], "lon": s["lon"],
            "factors": factors, "confidence": confidence, "raw": raw, "provenance": provenance,
            "features": s["features"], "well_known": s["well_known"],
            "why": s["why"], "breaks_down": s["breaks_down"],
            "image_url": previous.get(s["id"], {}).get("image_url"),
            "image_credit": previous.get(s["id"], {}).get("image_credit"),
        })
        print(f"  {s['id']:<14} ok" if s["id"] not in dict(problems) else f"  {s['id']:<14} FALLBACK", flush=True)

    targets = []
    for t in targets_raw:
        r = t["raw"]
        factors = {"slope": norm_slope(r["slope_deg"]), "roughness": norm_rough(r["roughness_m"]),
                   "temp_range": norm_temp(r["temp_range_K"]), "aridity": 1.0, "basaltic": r["basaltic"]}
        targets.append({
            "id": t["id"], "name": t["name"], "body": t["body"], "lat": t["lat"], "lon": t["lon"],
            "blurb": t["blurb"], "factors": factors, "raw": r,
            "confidence": ({f: t["confidence"].get(f, "estimated") for f in factors}
                           if isinstance(t.get("confidence"), dict)
                           else {f: t.get("confidence", "estimated") for f in factors}),
            "provenance": {"all": t["source"]},
        })

    all_estimated = all(v == "estimated" for t in targets for v in t["confidence"].values())
    meta = {
        "version": f"build-{dt.date.today().isoformat()}" + ("-placeholder-targets" if all_estimated else ""),
        "note": ("Earth values are sampled from open data. Moon/Mars target values are still placeholders - "
                 "see backend/pipeline/targets.json." if all_estimated else "Built from open data."),
        "factors": FACTOR_META,
        "normalization": NORM,
        "confidence_values": ["measured", "estimated"],
        "assumption": "Moon and Mars have no vegetation or rainfall. Aridity is compared as a relative proxy.",
        "data_sources": [
            "NASA POWER climatology (power.larc.nasa.gov)",
            "OpenTopoData elevation API (opentopodata.org)",
            "Moon/Mars targets: see each target's provenance (LOLA, Diviner, MOLA, THEMIS via NASA PDS)",
        ],
    }
    if problems:
        print("\nFell back to previous values for:", file=sys.stderr)
        for i, msg in problems:
            print(f"  {i}: {msg}", file=sys.stderr)
    return {"meta": meta, "targets": targets, "candidates": candidates}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="use cached API responses only")
    ap.add_argument("--dataset", default="mapzen", help="OpenTopoData dataset (mapzen, aster30m, srtm30m, ...)")
    args = ap.parse_args()
    out = build(args)
    for p in (ROOT / "data" / "sites.json", ROOT / "frontend" / "data" / "sites.json"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, indent=2))
        print("wrote", p.relative_to(ROOT))


if __name__ == "__main__":
    main()
