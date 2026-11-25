# Satellite Imagery Downloader 

This repo has three small scripts that each download free satellite or aerial imagery for an area you choose. Each one does the same four things:

1. **Finds** the best available image for your area.
2. **Downloads only your area**, selects a few tiles not whole region.
3. **Combines the color channels** (bands) into one GeoTIFF you can open in QGIS, ArcGIS or Python.
4. **Optimizes the image for viewing** by making a contrast-boosted JPEG, because raw satellite data usually looks dull.

| File | Imagery | Detail | Coverage | Best for |
|---|---|---|---|---|
| `1_landsat.py` | Landsat (8 and 9 for recent dates) | 30 m per pixel | Whole world, archive back to 1972 | Big areas, long history, seasonal change |
| `2_sentinel2.py` | Sentinel-2 | 10 m per pixel | Whole world, 2015 to today, new image every ~5 days | Sharper regional views, vegetation, water |
| `3_naip.py` | NAIP aerial photos | roughly 0.3 to 1 m per pixel | USA only, refreshed every few years | Street-level detail, small areas |

All three use the **Microsoft Planetary Computer**, which is free, needs **no account or API key**, and works the same way for each dataset. Learn one script and you've learned all three.

---

## 1. One-time setup

You need Python 3 and a few packages. In Terminal (Mac) or a command prompt:

```
python3 -m pip install pystac-client planetary-computer rasterio numpy pillow
```

Notes:
- If you see `pip: command not found`, use `python3 -m pip` exactly as written above.
- Warnings like "script X is installed in ... which is not on PATH" are harmless. You can ignore them.
- If you get an "externally-managed-environment" error, make a virtual environment first:
  ```
  python3 -m venv sat-env
  source sat-env/bin/activate
  python -m pip install pystac-client planetary-computer rasterio numpy pillow
  ```
  Run `source sat-env/bin/activate` again in any new terminal window before using the scripts.

## 2. Pick your area (the one thing you must edit)

Every script has a settings block near the top with `BBOX = (west, south, east, north)`. These are longitude and latitude in decimal degrees.

The easiest way to get the numbers is [bboxfinder.com](http://bboxfinder.com). Draw a rectangle and copy the coordinates. Note that it lists them in the order **west, south, east, north**.

**Keep the box small.** Bigger boxes mean bigger files and longer waits.

| Service | A sensible box size |
|---|---|
| Landsat | up to about 50 to 100 km across |
| Sentinel-2 | up to about 20 to 30 km across |
| NAIP | 1 to 5 km across |

Each script stops with a clear message if your box would produce more than 100 million pixels, which is the `MAX_PIXELS` safety limit in the settings.

## 3. Run a script

Open a terminal in the folder with the scripts and run one:

```
python3 1_landsat.py
python3 2_sentinel2.py
python3 3_naip.py
```

Each prints its progress and writes two files into an `output/` folder:

- `*_stack.tif`: your imagery with all bands combined (**use this for analysis and GIS**)
- `*_preview.jpg`: a brightened picture (**use this for looking, sharing, slides**)

---

## 4. Walkthrough of each service

### Landsat (`1_landsat.py`)

Landsat is the longest-running satellite imagery record, and this script uses Collection 2, Level 2 data, which is corrected to show the ground surface. For recent dates that means Landsat 8 and 9. Set an older `DATE_RANGE` and you'll get the earlier satellites instead. A scene covers about 185 × 185 km, so it suits regional views, and the 30 m pixels mean you can't zoom in on individual buildings.

Settings you'll edit:
- `BBOX`: your area.
- `DATE_RANGE`: for example `"2025-06-01/2025-09-30"`. Pick a season. The script chooses the clearest scene inside it.
- `MAX_CLOUD`: the cloud limit in percent. Raise it if the script says nothing was found.
- `BANDS`: which channels to combine. The default `["red", "green", "blue"]` gives a normal color photo. Add `"nir08"` (near infrared) for vegetation analysis, or `"lwir11"` for surface temperature.

What happens:
1. It searches for scenes covering your whole box, below your cloud limit, and picks the least cloudy.
2. It opens each band file remotely and reads just your area.
3. It stacks the bands into `landsat_stack.tif` and writes `landsat_preview.jpg`.

Landsat Level 2 values are scaled integers. To get true surface reflectance (0 to 1): `reflectance = value × 0.0000275 − 0.2`.

### Sentinel-2 (`2_sentinel2.py`)

Sentinel-2 is a European satellite pair that photographs the whole land surface roughly every five days, with 10 m pixels. It's the best free choice when Landsat is too blurry but you still want a worldwide, recent, regularly updated image.

Settings are the same as Landsat, except the band names are different:
- `B04` = red, `B03` = green, `B02` = blue, `B08` = near infrared.
- The default `BANDS = ["B04", "B03", "B02"]` gives a true-color image.
- Stick to those four bands. Other Sentinel-2 bands have different pixel sizes (20 m or 60 m) and won't line up with the 10 m ones in this simple script.

Sentinel-2 values are stored as integers of reflectance × 10,000 (newer scenes also carry a 1,000 offset). Check the scene's metadata if you need exact reflectance.

### NAIP (`3_naip.py`)

NAIP (National Agriculture Imagery Program) is aerial photography flown from planes over the continental US and Hawaii. It's much sharper than any satellite option here, and it's the right choice for neighborhoods, campuses, farms and small sites. The trade-offs are that it covers only the US, and each area is photographed only every few years.

NAIP tiles arrive with red, green, blue and near-infrared **already combined in a single file**, so this script skips the stacking step and just crops your area.

Settings:
- `BBOX`: keep it small, a few km at most. The default is the National Mall in Washington, DC.
- `DATE_RANGE`: the script uses the newest tile inside it.
- `RGB_ONLY`: set to `True` to drop the near-infrared band and make a smaller file.

Because NAIP tiles are small, your whole box must sit inside **one** tile. If the script says no single tile covers your box, shrink the box or shift it away from where tiles meet.

---

## 5. What the scripts do to "combine" and "optimize"

**Combining channels.** Landsat and Sentinel-2 publish each color channel as a separate file. The scripts read the same pixel window from each band and write them into one multi-band GeoTIFF. Each band is labeled (`red`, `green`, ...), so QGIS and similar programs show the names. The file keeps the map projection and location, so it drops into GIS software in the right place. NAIP is already combined, so the script only crops it.

**Optimizing.** Two kinds of optimization happen, and it helps to know the difference.

- **File size.** The GeoTIFF uses lossless compression (`deflate`), which shrinks it without changing a single value.
- **Appearance.** Raw satellite values usually occupy only a narrow slice of the available range, so the picture looks flat or hazy. For the preview JPEG, each band is **stretched**: the darkest 2% and brightest 2% of values are ignored, and the rest is spread across the full range. A small brightness adjustment follows. The stretch is applied to each band separately, which also quietly corrects color tint from haze.

**The preview JPEG is not data.** The stretch changes the numbers, so never use the JPEG for measurements. Use the `.tif` for analysis.

Two settings to tweak the look: `BRIGHTNESS` (above 1 is brighter) and the `(2, 98)` percentile pair inside `save_preview`. For a stronger stretch try `(5, 95)`. For a gentler one try `(0.5, 99.5)`.

Note on image size: 
The preview JPEG's pixel dimensions come straight from the BBOX and the imagery's pixel size. The scripts never resize it.

Pixel dimensions = box size ÷ pixel size

Landsat: 30 m per pixel, so a 60 km wide box is about 2,000 pixels wide.
Sentinel-2: 10 m per pixel, so a 20 km wide box is about 2,000 pixels wide.
NAIP: 0.3 to 1 m per pixel depending on the state and year, so a 2 km wide box is about 2,000 to 7,000 pixels wide. 

---

## 6. Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| `No scene fully covers your box` | Widen `DATE_RANGE`, raise `MAX_CLOUD`, or shrink `BBOX`. |
| `No single NAIP tile covers your box` | Shrink the box or shift it. NAIP is also US-only. |
| `That area is too big` | Shrink `BBOX`, or raise `MAX_PIXELS` if you really want it. |
| Seems to hang | Almost always a box that is too large. Stop it with Ctrl+C and use a smaller area. |
| Black or transparent patches | Empty (no-data) pixels, usually at scene edges. They are marked as no-data in the `.tif`. |
| Image looks washed out in QGIS | That's the program's default display. Raw data really is flat. Use the preview JPEG, or set a manual min/max stretch in the layer styling. |
| `ModuleNotFoundError` | A package isn't installed. Re-run the setup command in section 1. |
| Wrong place on the map | Coordinates must be **longitude first, then latitude**. In the western US and Americas, longitude is negative. |

## 7. Where to go next

- **Browsing visually:** USGS EarthExplorer and GloVis let you click through Landsat scenes, with a free USGS account for downloads.
- **Analysis without downloading:** Google Earth Engine is free for non-commercial use and handles large-scale analysis in the cloud.
- **Bigger projects:** the Planetary Computer's STAC catalog also hosts elevation, land cover and climate data. The same `pystac-client` pattern in these scripts works for them.
