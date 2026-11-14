#!/usr/bin/env python3
"""Find the highest points near a feature in a projected DEM (e.g. LOLA south-polar GeoTIFF).

Use it instead of QGIS to locate a crater RIM or a mountain summit:

  # crater rim: search a ring 8-13 km from the crater centre (Shackleton is ~21 km wide)
  python backend/pipeline/find_high_points.py LDEM_80S_80MPP_ADJ.TIF --lat -89.9 --lon 129.3 --rmin-km 8 --rmax-km 13

  # mountain/massif: search everything within 10 km of a rough centre
  python backend/pipeline/find_high_points.py LDEM_80S_80MPP_ADJ.TIF --lat -86.0 --lon 0 --rmin-km 0 --rmax-km 10

It prints the top candidate spots (lat, lon, elevation), separated by at least --sep-km, so you can
pass the chosen lat/lon to terrain_from_raster.py. Get the rough centre of a named feature from the
USGS Gazetteer of Planetary Nomenclature or Wikipedia. Works for projected rasters only.
"""
import argparse

import numpy as np
import rasterio
from pyproj import CRS as PCRS, Transformer


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dem")
    ap.add_argument("--lat", type=float, required=True, help="rough centre latitude")
    ap.add_argument("--lon", type=float, required=True, help="rough centre longitude (east positive)")
    ap.add_argument("--rmin-km", type=float, default=0.0)
    ap.add_argument("--rmax-km", type=float, required=True)
    ap.add_argument("--sep-km", type=float, default=3.0, help="minimum distance between reported spots")
    ap.add_argument("--top", type=int, default=5)
    a = ap.parse_args()

    with rasterio.open(a.dem) as ds:
        if ds.crs is None or ds.crs.is_geographic:
            raise SystemExit("this helper needs a projected raster (like the LOLA polar-stereographic TIFs)")
        proj = PCRS.from_wkt(ds.crs.to_wkt())
        fwd = Transformer.from_crs(proj.geodetic_crs, proj, always_xy=True)
        back = Transformer.from_crs(proj, proj.geodetic_crs, always_xy=True)
        cx, cy = fwd.transform(a.lon, a.lat)
        inv = ~ds.transform
        r = a.rmax_km * 1000.0
        corners = [inv * (cx + sx * r, cy + sy * r) for sx in (-1, 1) for sy in (-1, 1)]
        c0 = int(np.floor(min(c for c, _ in corners))) - 1
        c1 = int(np.ceil(max(c for c, _ in corners))) + 1
        r0 = int(np.floor(min(rr for _, rr in corners))) - 1
        r1 = int(np.ceil(max(rr for _, rr in corners))) + 1
        if c0 < 0 or r0 < 0 or c1 > ds.width or r1 > ds.height:
            raise SystemExit("the search area is not fully inside the raster; check lat/lon or lower --rmax-km")
        z = ds.read(1, window=((r0, r1), (c0, c1)), masked=True).astype("float64")
        rows, cols = np.mgrid[r0:r1, c0:c1]
        xs, ys = ds.transform * (cols + 0.5, rows + 0.5)

    dist = np.hypot(xs - cx, ys - cy)
    ok = (dist >= a.rmin_km * 1000) & (dist <= a.rmax_km * 1000) & ~np.ma.getmaskarray(z)
    if not ok.any():
        raise SystemExit("no valid pixels in the search area")
    zz = np.where(ok, np.ma.getdata(z), -np.inf)
    order = np.argsort(zz.ravel())[::-1]

    picked = []
    sep = a.sep_km * 1000
    for idx in order:
        if not np.isfinite(zz.ravel()[idx]):
            break
        x, y = xs.ravel()[idx], ys.ravel()[idx]
        if all(np.hypot(x - px, y - py) >= sep for px, py, _ in picked):
            picked.append((x, y, zz.ravel()[idx]))
        if len(picked) >= a.top:
            break

    print(f"search: {a.rmin_km}-{a.rmax_km} km around lat {a.lat}, lon {a.lon}  (pixel {abs(ds.transform.a):.0f} m)")
    print(f"{'#':>2} {'lat':>9} {'lon':>9} {'elev_m':>9} {'km_from_centre':>15}")
    for i, (x, y, e) in enumerate(picked, 1):
        lon, lat = back.transform(x, y)
        print(f"{i:>2} {lat:>9.4f} {lon:>9.4f} {e:>9.1f} {np.hypot(x - cx, y - cy) / 1000:>15.2f}")
    print("\nNext: python backend/pipeline/terrain_from_raster.py <dem> --lat <lat> --lon <lon>")


if __name__ == "__main__":
    main()