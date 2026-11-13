# Changelog

## 0.11.0 (Nov 12, 2026)

- **After updating:** click **Import from game files** in the Maps page once. It makes the night map, the road
  grid for navigation along roads and the province of each marker; until then those three are missing.
- The map page opens faster: maps and markers are fetched once instead of twice, and the PC sends the
  marker list only when it changed.
- Ore, plants, chests and animals (about 39 000 markers that start switched off) are loaded only when you
  switch one of them on or search: the first load is about 7 times smaller.
- Ticking a marker as found redraws only that marker.
- **Nearest to you**: the marker panel lists the closest markers you have not found yet, with distance and direction.
- **Navigate**: on a marker's card, or after a long press anywhere on the map. A line leads there, an arrow at the
  screen edge shows the way when it is out of view, and it ends when you arrive. Distances now say the direction
  and, where it matters, "12 m above you" or "below".
- **Long press** on the map: coordinates of that spot (copy), distance from you, add a marker there.
- **Import again is quick**: maps that would come out the same (same game version and quality) are not rendered again,
  so "Import from game files" after an app update only refreshes the markers.
- The map page loads its program compressed and keeps it cached; a slow tablet is sent the newest position instead of a queue.
- **A new look for the Windows app**: a navigation bar at the side (Connect, Maps, Settings, Activity, About), pages with
  cards, and light and dark colours that follow Windows. Ctrl+1 to Ctrl+5 switch pages.
- **Get started**: on first use the Connect page lists the three steps (find the game, make the map, connect a device) and
  ticks them off.
- **Import**: shows about how long is left, can be cancelled, and Windows notifies you when it is done.
- **Connected devices**: the Connect page lists which tablets and phones are connected, and since when.
- **Calmer screen**: while the map follows you, the buttons fade away after a few seconds and come back at a touch
  (Settings → "Hide the buttons while following"). The panel slides in and out.
- **Tips on first use**, and "Show the tips again" in Settings.
- **Quick profiles**: hold the Profiles button for a list of your recent profiles.
- **When the PC is not reachable** the map turns grey and says so, with "Try again"; a thin bar shows map tiles loading.
- **A phone held sideways** gets the toolbar on the left. The search lists names that start with your word first, then
  the nearest, and says how many more there are.
- **Tidier map page**: the marker card has a row of icon buttons (Found, Navigate, Show, Edit, Delete); questions such as
  "Delete?" and "Rename" are part of the page instead of browser pop-ups; number circles take the colour of the markers
  they hold; the selected marker always shows its name, and names are readable on the dark maps.
- **Find a category**: the search box also lists categories; "only" shows just that one.
- **On phones** the panel is a bottom sheet: drag its grip, or tap it, for a strip, half or the full screen.
- **A real night map**: the import now also makes the Pywel map in night colours; "Night colours" in Settings shows it
  (until the next import it stays a colour filter).
- **Progress by province** in the marker panel, for the categories you have switched on.
- **Found ticks survive game patches**: when a patch moves an ore vein or chest slightly, its tick moves with it.
- **Measure**: long-press a spot, "Measure from here", then open any marker or spot to see the distance between them.
- Own markers can have a **colour**; a **route** through markers goes on after a reload; the **trail** is kept when the app restarts.
- **Navigate along roads**: on the Pywel map the route follows the game's roads and shows the distance by road. It needs
  one more **Import from game files** (the import now also stores a small road grid). Settings can switch it off.
- **Route through the markers on screen**: in the marker panel. It orders the markers you have not found into a short
  route and leads from one to the next; "Next" skips a stop.
- **Your own markers**: a form instead of a pop-up, with notes and a kind (chest, cave, ore, ...) that picks the icon;
  Edit changes them later and can move them to where you stand or to a tap on the map.
- **Game language**: the Maps page has a language for the names the game gives to places and resources (15 languages);
  import again after changing it. Category names stay English.
- **Heat map when zoomed out**: a switch in the marker panel shows where markers are dense instead of numbered circles.
- **Found by itself**: per category, the PC can tick a marker when you stand at it ("Tick when I get there" on the
  marker's card), also while the tablet sleeps.
- **Comes back after**: per category, a found tick can end by itself after 1 hour to 7 days (ore, plants).
- **Backup**: Settings saves found ticks, your markers, rules and profiles as one file, and restores it (adds what is
  missing, removes nothing).
- **Trail**: the map shows where you have been since the app started; every device sees it. Settings can hide or clear it.
- **Minimal view**: only the map, heading up, zooming out when you ride or sail. **Night colours** for the Pywel map.
- Found progress for the realm and a bar per group in the marker panel.
- **Import from game files is about six times faster** (38 seconds instead of almost 4 minutes on the test PC):
  open sea is no longer drawn tile by tile, tiles are made on several processor cores, and the game icons
  are found without indexing the whole install. The map looks the same.
- A **compass** button appears while the map is turned; tap it for north up. A **scale bar** shows distances.
- Less work on the tablet while following the player (the page no longer redraws its buttons 30 times a second).
- Only the map page itself can change markers, progress and profiles; requests from other websites are refused.

## 0.10.0 (Nov 8, 2026)

- **After updating:** click **Import from game files** in the Maps tab (or **Update map files** on
  the main page) once, so the new markers and icons are made from your game files.
- **Supports the "Charting the Unknown" DLC** and game patch 2.04.08 (exe 1.0.0.3576). If the DLC is
  installed, **Import from game files** now adds its content:
  - the islands and their coasts, island and sea caves, sunken ruins, island ruins, villages,
    residences, sanctums and more (about 140 places), with the game's own names;
  - Abyss ruins, Abyss Cressets, ocean puzzles and Relic Collectors at sea, and rest points on the islands;
  - new resources (off by default): manganese nodules, shiny minerals, malachite, hydrothermal
    deposits, obsidian, golden coral, sea fan coral, reefs, natural pearls, ambergris, anchorages and
    businesses for rent.
- Without the DLC, nothing changes.
- **The game's own map icons for the markers**: ores, plants, corals, crafting stations, shops,
  bells, Abyss gates, animals, caves, forts and more now show the icon the game uses, on the usual
  coloured disc. They are taken from your game files and stay on your PC. **Settings → Game icons**
  switches back to the simple icons.
- The markers panel and the settings stay where you scrolled to when you tick a category or a
  switch (they jumped back to the top).
- The Relic Collectors are no longer named "Relic Collector · Collector".

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
