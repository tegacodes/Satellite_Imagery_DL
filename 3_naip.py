"""
NAIP downloader  (aerial photos, ~0.3-1 m per pixel, USA only)

What this script does:
  1. Searches Microsoft's free Planetary Computer for the newest NAIP tiles that
     cover your area (if your box crosses a tile edge, it uses several tiles).
  2. Reads ONLY your area and joins the tiles into one image (no big downloads).
     NAIP already comes with red, green, blue and near-infrared in ONE file per
     tile, so there are no separate bands to combine.
  3. Saves a multi-band GeoTIFF                       -> output/naip_stack.tif
  4. Makes a contrast-boosted picture for viewing     -> output/naip_preview.jpg

Setup (once):  python3 -m pip install pystac-client planetary-computer rasterio numpy pillow
Run:           python3 3_naip.py
No account or API key needed.
"""
import math
import os
import sys

import numpy as np
import planetary_computer
import rasterio
from PIL import Image
from pystac_client import Client
from rasterio.merge import merge
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds

# ======================= SETTINGS: edit these =======================
# Your area as (west, south, east, north) in longitude/latitude.
# KEEP IT SMALL: NAIP pixels are tiny, so a few km across is plenty.
# Remember: longitude comes first, and is NEGATIVE in the USA.
# Tip: draw a box and read the numbers at http://bboxfinder.com
BBOX = (-73.983221,40.762406,-73.968716,40.772969)   # the National Mall, Washington DC

DATE_RANGE = "2015-01-01/2026-12-31"        # the newest imagery in this range is used
RGB_ONLY = False                            # True = skip the near-infrared band
BRIGHTNESS = 1.1                            # preview only: >1 brighter, <1 darker
MAX_PIXELS = 100_000_000                    # safety limit
OUT_DIR = "output"
# ====================================================================


def covers(tiles):
    """True if the tiles together cover the whole BBOX (checked on a grid of points)."""
    west, south, east, north = BBOX
    for i in range(11):
        for j in range(11):
            x = west + (east - west) * i / 10
            y = south + (north - south) * j / 10
            if not any(t.bbox[0] <= x <= t.bbox[2] and t.bbox[1] <= y <= t.bbox[3] for t in tiles):
                return False
    return True


def find_tiles():
    """Return the tiles needed to cover BBOX, newest first."""
    catalog = Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,  # lets us read the files
    )
    search = catalog.search(collections=["naip"], bbox=BBOX, datetime=DATE_RANGE, max_items=200)
    found = sorted(search.items(), key=lambda t: t.datetime, reverse=True)
    print(f"  {len(found)} tile(s) touch your box")
    if not found:
        sys.exit("No NAIP imagery found for this box.\n"
                 "NAIP only covers the USA. Check BBOX is (west, south, east, north)\n"
                 "with longitude FIRST and negative, e.g. (-77.05, 38.88, -77.02, 38.90).")

    # Prefer a single survey year that covers everything...
    for year in sorted({t.datetime.year for t in found}, reverse=True):
        tiles = [t for t in found if t.datetime.year == year]
        if covers(tiles):
            print(f"  Using {len(tiles)} tile(s) from {year}")
            return tiles
    # ...otherwise mix years (newest wins where they overlap).
    if covers(found):
        years = sorted({t.datetime.year for t in found}, reverse=True)
        print(f"  Mixing survey years {years} (newest on top)")
        return found
    sys.exit("NAIP tiles exist here, but they leave a gap in your box.\n"
             "Part of it may be outside NAIP coverage (water, or outside the USA). "
             "Try a smaller BBOX.")


def read_area(tiles):
    """Read just our box from the tiles and join them into one image."""
    env = dict(GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="1",
               GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR")
    with rasterio.Env(**env):
        opened = [rasterio.open(t if isinstance(t, str) else t.assets["image"].href) for t in tiles]
        crs = opened[0].crs
        # tiles near a UTM zone edge can use another projection: convert on the fly
        sources = [d if d.crs == crs else WarpedVRT(d, crs=crs) for d in opened]
        left, bottom, right, top = transform_bounds("EPSG:4326", crs, *BBOX)
        pixel = opened[0].res[0]
        # snap the box to the pixel grid so tiles line up exactly at their seams
        x0, y0 = opened[0].transform.c, opened[0].transform.f
        left = x0 + math.floor((left - x0) / pixel) * pixel
        right = x0 + math.ceil((right - x0) / pixel) * pixel
        top = y0 - math.floor((y0 - top) / pixel) * pixel
        bottom = y0 - math.ceil((y0 - bottom) / pixel) * pixel
        bounds = (left, bottom, right, top)
        n_wide, n_high = int((bounds[2] - bounds[0]) / pixel), int((bounds[3] - bounds[1]) / pixel)
        print(f"  Area is about {n_wide} x {n_high} pixels ({pixel:.2f} m each)")
        if n_wide * n_high > MAX_PIXELS:
            sys.exit("That area is too big. Use a smaller BBOX (or raise MAX_PIXELS).")
        print("  reading and joining tiles ...")
        indexes = [1, 2, 3] if RGB_ONLY else [1, 2, 3, 4]
        data, transform = merge(sources, bounds=bounds, indexes=indexes, nodata=0)
        for d in sources + opened:
            d.close()
    return data, transform, crs


def save_geotiff(path, data, transform, crs, names):
    """Write all bands into ONE file. Compression keeps it small."""
    with rasterio.open(path, "w", driver="GTiff", height=data.shape[1], width=data.shape[2],
                       count=data.shape[0], dtype=data.dtype, crs=crs, transform=transform,
                       compress="deflate", predictor=2, nodata=0) as dst:
        dst.write(data)
        for i, name in enumerate(names, start=1):
            dst.set_band_description(i, name)


def save_preview(path, data):
    """Contrast-stretch the first 3 bands and save a JPEG (for LOOKING, not analysis)."""
    rgb = data[:3].astype("float32")
    valid = rgb.max(axis=0) > 0                      # ignore empty (0) pixels
    out = np.zeros_like(rgb)
    for i in range(3):
        low, high = np.percentile(rgb[i][valid], (2, 98))   # ignore extreme 2% each end
        out[i] = np.clip((rgb[i] - low) / (high - low + 1e-6), 0, 1)
    out = out ** (1 / BRIGHTNESS)
    picture = (np.moveaxis(out, 0, -1) * 255).astype("uint8")
    Image.fromarray(picture).save(path, quality=90)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Step 1/3: searching ...")
    tiles = find_tiles()

    print("Step 2/3: downloading your area ...")
    data, transform, crs = read_area(tiles)

    print("Step 3/3: saving ...")
    names = ["red", "green", "blue"] + ([] if RGB_ONLY else ["nir"])
    save_geotiff(f"{OUT_DIR}/naip_stack.tif", data, transform, crs, names)
    save_preview(f"{OUT_DIR}/naip_preview.jpg", data)
    print(f"Done! See the '{OUT_DIR}' folder.")


if __name__ == "__main__":
    main()