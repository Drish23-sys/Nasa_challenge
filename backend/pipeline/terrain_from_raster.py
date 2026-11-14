#!/usr/bin/env python3
"""Slope + roughness for a Moon/Mars/Earth site from a DEM GeoTIFF you downloaded.

It measures the target EXACTLY like build_sites.py measures the Earth sites: a 5x5 grid of points
500 m apart (a ~2 km patch) centred on the lat/lon you give, then the same slope and roughness
formulas. That keeps the Moon/Mars numbers comparable to the Earth numbers.

  pip install rasterio pyproj numpy
  python backend/pipeline/terrain_from_raster.py LDEM_80S_80MPP_ADJ.TIF --lat -89.9 --lon 129.8

Works with projected rasters (e.g. LOLA south-polar stereographic, in metres) and geographic
rasters (e.g. MOLA, in degrees). Lat/lon are converted with the RASTER'S OWN body, never Earth's.
Put the printed slope_deg and roughness_m into backend/pipeline/targets.json.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS as PCRS, Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sites import GRID_N, GRID_SPACING_M, terrain_stats  # noqa: E402  (same formulas as the Earth sites)


def sample_grid(ds, lat, lon, n=GRID_N, spacing=GRID_SPACING_M):
    half = (n - 1) / 2
    offsets = [(i - half) * spacing for i in range(n)]  # metres
    proj = PCRS.from_wkt(ds.crs.to_wkt())
    tr = Transformer.from_crs(proj.geodetic_crs, proj, always_xy=True)
    if ds.crs.is_geographic:
        radius = proj.ellipsoid.semi_major_metre
        m_per_deg = 2 * np.pi * radius / 360.0
        pts = [(lon + dx / (m_per_deg * max(np.cos(np.radians(lat)), 0.05)), lat + dy / m_per_deg)
               for dy in offsets for dx in offsets]
        xy = pts
        cx, cy = lon, lat
    else:
        cx, cy = tr.transform(lon, lat)
        xy = [(cx + dx, cy + dy) for dy in offsets for dx in offsets]
    print(f"centre in raster coordinates: x={cx:.4f}, y={cy:.4f}")

    # bilinear interpolation (nearest-pixel sampling adds fake roughness when pixels are
    # comparable to the 500 m grid spacing)
    inv = ~ds.transform
    cols, rows = zip(*[inv * (x, y) for x, y in xy])
    cols, rows = np.array(cols), np.array(rows)
    if cols.min() < 0 or rows.min() < 0 or cols.max() > ds.width - 1 or rows.max() > ds.height - 1:
        raise SystemExit("this site (or part of its 2 km patch) is outside the raster. "
                         "Check lat/lon and longitude convention, or download a raster that covers it.")
    c0, r0 = int(np.floor(cols.min())), int(np.floor(rows.min()))
    c1, r1 = int(np.ceil(cols.max())) + 1, int(np.ceil(rows.max())) + 1
    block = ds.read(1, window=((r0, r1 + 1), (c0, c1 + 1)), boundless=True, masked=True).astype("float64")
    if np.ma.is_masked(block) and np.ma.getmaskarray(block).any():
        raise SystemExit("the patch contains no-data pixels; pick a spot with full coverage")
    block = np.ma.getdata(block)
    vals = []
    for c, r in zip(cols, rows):
        fc, fr = c - c0, r - r0
        i, j = int(np.floor(fr)), int(np.floor(fc))
        di, dj = fr - i, fc - j
        v = (block[i, j] * (1 - di) * (1 - dj) + block[i, j + 1] * (1 - di) * dj
             + block[i + 1, j] * di * (1 - dj) + block[i + 1, j + 1] * di * dj)
        vals.append(v)
    vals = np.array(vals)
    if not np.isfinite(vals).all():
        raise SystemExit("non-finite elevations in the patch; check the raster")
    return vals.reshape(n, n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dem")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True, help="east-positive longitude, same convention as the raster")
    a = ap.parse_args()

    with rasterio.open(a.dem) as ds:
        if ds.crs is None:
            raise SystemExit("raster has no CRS; cannot place the site")
        px = abs(ds.transform.a)
        print(f"raster pixel ~{px:.4g} {'deg' if ds.crs.is_geographic else 'm'}")
        z = sample_grid(ds, a.lat, a.lon)

    slope, rough = terrain_stats(z, GRID_SPACING_M)
    print(f"elevation range in patch: {z.min():.1f} to {z.max():.1f} m (mean {z.mean():.1f})")
    print(f"slope_deg   = {slope:.2f}")
    print(f"roughness_m = {rough:.2f}")


if __name__ == "__main__":
    main()