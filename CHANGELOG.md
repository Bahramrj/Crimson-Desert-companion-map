# Changelog

## 0.9.0 (Nov 2, 2026)

- **Supports game patch 2.04.05** (exe 1.0.0.3479, Steam build 26361232), base game. The
  "Charting the Unknown" DLC is not included or tested. Version 0.8.0 and older cannot read the
  game files of patch 2.04.
- **After updating:** click **Import from game files** (or **Update map files** on the main page)
  once, so the map and markers are made from the new game files.
- **Bigger map.** Patch 2.04 draws a larger world map that takes in the sea south and east of
  Pywel; the map now covers it too. Markers out at sea are not available yet.
- All marker types work again with the new game files: places, points of interest, rest points,
  resources and treasures, animals and the province names.
- The map import takes about 2 minutes per realm (was 1); "High resolution" renders Pywel at
  51 200 px.
- Cleaner map edges: contour lines fade out where the game's height data ends, and province borders
  are only drawn between real provinces.
- The settings and markers panels keep the keyboard focus when they refresh.

## 0.8.0 (Oct 27, 2026)

- Sharper map: one-pixel coasts, rivers and roads, higher tile quality, full resolution on iPads
  and phones.
- New markers: wild-animal spawn areas (16 species, off by default) and the 60 Abyss Cressets.
- Places sorted by their English names too (Fishing spots, Trading posts & markets, Landmarks).
- Refreshed look of the device page and the Windows app.

## 0.7.0 (Oct 26, 2026)

- Resources and treasures from the game files: ore, plants, crafting stations, chests and more
  (about 16 000 markers, off by default).
- Version line on the Windows app's main page: map and game version synced, or "Update map files".
- VPN adapters hidden; the app follows network changes.

Earlier versions: see the git history.
