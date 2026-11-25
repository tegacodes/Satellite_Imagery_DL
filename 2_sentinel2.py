"""
SENTINEL-2 downloader  (10 m per pixel, 2015 -> today, whole world, every ~5 days)

What this script does:
  1. Searches Microsoft's free Planetary Computer for the least-cloudy Sentinel-2
     scene that covers your area and date range.
  2. Reads ONLY your area from each color band (no huge whole-scene downloads).
  3. Combines the bands into ONE multi-band GeoTIFF   -> output/sentinel2_stack.tif
  4. Makes a contrast-boosted picture for viewing     -> output/sentinel2_preview.jpg

Setup (once):  python3 -m pip install pystac-client planetary-computer rasterio numpy pillow
Run:           python3 2_sentinel2.py
No account or API key needed.
"""
import os
import sys

import numpy as np
import planetary_computer
import rasterio
from PIL import Image
from pystac_client import Client
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds

# ======================= SETTINGS: edit these =======================
# Your area as (west, south, east, north) in longitude/latitude.
# Tip: draw a box and read the numbers at http://bboxfinder.com
BBOX = (-77.12, 38.82, -76.93, 38.98)       # Washington, DC

DATE_RANGE = "2025-06-01/2025-09-30"        # start/end, YYYY-MM-DD
MAX_CLOUD = 20                              # skip scenes cloudier than this (%)

# Which bands to combine. The first three become the picture (red, green, blue).
# Sentinel-2 names: B04=red, B03=green, B02=blue, B08=near infrared,
# B11 / B12 = shortwave infrared (B11 and B12 are 20 m; mixing them with 10 m
# bands will not line up, so keep to B02/B03/B04/B08 here).
BANDS = ["B04", "B03", "B02"]

BRIGHTNESS = 1.1                            # preview only: >1 brighter, <1 darker
MAX_PIXELS = 100_000_000                    # safety limit so you don't grab too much
OUT_DIR = "output"
# ====================================================================


def find_scene():
    """Return the least-cloudy scene that fully covers BBOX."""
    catalog = Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,  # lets us read the files
    )
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=BBOX,
        datetime=DATE_RANGE,
        query={"eo:cloud_cover": {"lt": MAX_CLOUD}},
        max_items=100,
    )
    west, south, east, north = BBOX
    scenes = [
        i for i in search.items()
        if i.bbox[0] <= west and i.bbox[1] <= south and i.bbox[2] >= east and i.bbox[3] >= north
    ]
    if not scenes:
        sys.exit("No scene fully covers your box with those dates/cloud limit.\n"
                 "Try: a wider DATE_RANGE, a higher MAX_CLOUD, or a smaller BBOX.")
    return min(scenes, key=lambda s: s.properties["eo:cloud_cover"])


def read_area(hrefs):
    """Read just our box from each band file and stack them into one array."""
    arrays = []
    env = dict(GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="1",
               GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR")
    with rasterio.Env(**env):
        for n, href in enumerate(hrefs):
            with rasterio.open(href) as src:
                if n == 0:  # work out which pixels = our box (same for every band)
                    left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *BBOX)
                    w = from_bounds(left, bottom, right, top, transform=src.transform)
                    window = Window(int(w.col_off), int(w.row_off), int(w.width), int(w.height))
                    print(f"  Area is {window.width} x {window.height} pixels")
                    if window.width * window.height > MAX_PIXELS:
                        sys.exit("That area is too big. Use a smaller BBOX (or raise MAX_PIXELS).")
                    transform, crs = src.window_transform(window), src.crs
            print(f"  reading band {n + 1} of {len(hrefs)} ...")
            with rasterio.open(href) as src:
                arrays.append(src.read(1, window=window))
    return np.stack(arrays), transform, crs


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
    scene = find_scene()
    print(f"  Using {scene.id}  ({scene.datetime:%Y-%m-%d}, "
          f"{scene.properties['eo:cloud_cover']:.0f}% cloud)")

    print("Step 2/3: downloading your area ...")
    data, transform, crs = read_area([scene.assets[b].href for b in BANDS])

    print("Step 3/3: saving ...")
    save_geotiff(f"{OUT_DIR}/sentinel2_stack.tif", data, transform, crs, BANDS)
    save_preview(f"{OUT_DIR}/sentinel2_preview.jpg", data)
    print(f"Done! See the '{OUT_DIR}' folder.")


if __name__ == "__main__":
    main()
