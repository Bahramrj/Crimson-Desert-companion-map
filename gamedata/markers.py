"""Points of interest from the game's own data, as mapstore marker sets.

- Places: `factionnode` (castles, caves, camps, ...). English names and descriptions come from
  `knowledgeinfo` row `Knowledge_<node name>` -> knowledge.paloc ("Node_Her_HowlingCave" is
  "Howling Hollow"); without one the internal name is spelled out.
- Points: meditation spots, rest points and Abyss bridge gates (`fieldreviveinfo` types + `fieldreviveinfo_misc`
  positions from 2.04, `reviepointinfo` rows before).
- Points of interest: named objects placed in the levels (shops, Abyss gates and ruins,
  puzzles, challenges, faction buildings), plus the eight town bells from their level files.
- Resources & treasures: objects placed by type (ore, plants, crafting stations, chests, memory
  fragments, ...), named from gimmick.paloc; off in the marker panel until switched on.
- Animals: where wild animals spawn (`stageinfo` LevelSequencerSpawn_WildAnimal_* rows), one marker
  per area for the named species (boars, bison, eagles, ...); generic kinds ("medium land animal",
  "cliff bird") are left out.
- Regions: one label per province (Hernand, Pailune, ...) from the world-map region bitmap.
An installed DLC (dlc/<name>/) adds its own rows, placements and names (gamedata.archive): the
"Charting the Unknown" islands, sunken ruins, sea caves, residences, sea minerals and corals.
Positions are float32 x/y/z in the engine's own space.
"""

import logging
import math
import re

from gamedata import icons, levels, regions, worldmap
from gamedata.archive import ArchiveError
from gamedata.strings import load_strings, texts_in
from gamedata.rules import (  # noqa: F401  (the tables are also read as markers.<NAME>)
    BELL_TOWNS, REGIONS, PLACE_RULES, CRAFT_WORDS, LANDMARK, OTHER_PLACE, 
    REVIVE_RULES, REVIVE_TYPES, SHOP_KINDS, GROUPS, RESOURCE_RULES, ANIMALS, POI_CATEGORIES,
)
from gamedata.timing import timed
from gamedata.tables import first_position, grouped_points, placements, read_miscs, read_table, typed_placements
from mapstore.georef import WORLD

log = logging.getLogger("cdlivemap.gamedata")

ABYSS_Y = 1400.0     # same rule as the engine
LICENCE = "extracted from your own Crimson Desert install; personal use, do not share"
# The eight town bells: one level file each, mission_pororinvillage_bell_all_<town>.palevel; the bell
# sits in the middle of the level's bounding box. Their game titles ("Bell Tolling in Hernand") are
# knowledgeinfo rows Knowledge_Pororin_Bell_<town>.
BELL_LEVEL = "mission_pororinvillage_bell_all_"


def group_of(category):
    return GROUPS.get(category, "Locations")


RESOURCE_MATCH = [(cat, re.compile(rule, re.I)) for cat, _, _, rule in RESOURCE_RULES]


def singular(label):
    """'Small boxes' -> 'Small box', 'Camp facilities' -> 'Camp facility', 'Anvils' -> 'Anvil'."""
    for plural, one in (("ies", "y"), ("xes", "x"), ("s", "")):
        if label.endswith(plural):
            return label[:-len(plural)] + one
    return label


# Wild animal spawns (stageinfo): LevelSequencerSpawn_WildAnimal_m<x>_m<z>_<n>_Doc_<kind>[_NN]. The kind
# names the species for the big game; the rest are generic ("Land_Bird_Medium") and not marked.
ANIMAL_STAGE = re.compile(r"LevelSequencerSpawn_WildAnimal_m\d+_m\d+_\d+_Doc_(\w+?)(?:_\d+)?$", re.I)
ANIMAL_MATCH = [(cat, name, re.compile(rule, re.I)) for cat, _, name, rule in ANIMALS]
HERD_M = 75.0                   # spawn points of one species this close are one area
STAGE_PLACEHOLDER = (2.0, 204.2588)   # x, y every stage row also carries; never a real spot


def animal_kind(stage_name):
    """(category, marker name) for a wild-animal spawn stage, or None (other stages, generic kinds)."""
    m = ANIMAL_STAGE.match(stage_name)
    if not m:
        return None
    return next(((cat, name) for cat, name, rule in ANIMAL_MATCH if rule.match(m.group(1))), None)


def resource_category(gimmick):
    """Category id for a gimmickinfo row name, or None for objects that are not map-worthy."""
    return next((cat for cat, rule in RESOURCE_MATCH if rule.match(gimmick)), None)


CRESSET_KNOWLEDGE = "Knowledge_LevelGimmickIcon_StandStone"


def words(camel):
    """'SanctuaryofFirefliesCave' -> ['Sanctuary', 'of', 'Fireflies', 'Cave']."""
    camel = re.sub(r"of(?=[A-Z])", " of ", camel)
    return re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|of|\d+", camel)


def spell(parts):
    """Internal name parts -> readable words; numbers lose their leading zeros, roman numerals stay."""
    out = []
    for part in parts:
        if part.isdigit():
            out.append(str(int(part)))
        elif re.fullmatch(r"[IVX]+", part):
            out.append(part)
        else:
            out.extend(words(part[:1].upper() + part[1:]))
    text = " ".join(out)
    return text[:1].upper() + text[1:]


def place_name(internal):
    """'Node_Her_HernandCastle' -> 'Hernand Castle'; 'Node_Dem_RestArea_0086' -> 'Rest Area 86'."""
    parts = internal.split("_")
    parts = (parts[2:] or parts[1:]) if parts[0] == "Node" else parts      # Node_<region>_<Name>, or Node_<Name>
    if len(parts) > 1 and parts[0] == "Region":            # "Region_Cave_0017" -> "Cave 17"
        parts = parts[1:]
    return spell(parts) or internal


def _rule_match(tokens, text):
    for cat, _, keys in PLACE_RULES:
        # single words match whole words ("Den" is not "Garden"); CamelCase keys match as substrings
        if any(k in tokens or (sum(c.isupper() for c in k) > 1 and k in text) for k in keys):
            return cat
    return None


def place_category(internal, title=None):
    """Category of a faction node, from its internal name, else from its English name (`title`)."""
    parts = internal.split("_")
    tail = "_".join(parts[2:] or parts[1:])
    cat = _rule_match(set(words(tail.replace("_", " "))), tail)
    if cat or not title:
        return cat or OTHER_PLACE[0]
    tokens = re.findall(r"[A-Za-z']+", title)
    cat = _rule_match(set(tokens), title)
    if cat:
        return cat
    if any(t.lower().endswith(CRAFT_WORDS) for t in tokens):
        return "work"
    if set(tokens) & set(LANDMARK[2]):
        return LANDMARK[0]
    return OTHER_PLACE[0]


def poi_kind(name):
    """(category, display name) for a placed object, or None for objects that are not map-worthy."""
    parts = [p for p in name.split("_") if p]
    if m := re.match(r"AbyssGate_(\d+)", name):
        return "abyss-gate", f"Abyss Gate {int(m.group(1))}"
    if m := re.match(r"AbyssRuins_([A-Za-z]+)_(\d+)", name):
        return "abyss-ruins", f"Abyss Ruins ({REGIONS.get(m.group(1), spell([m.group(1)]))}) {int(m.group(2))}"
    if parts[0] == "Puzzle" and len(parts) > 1:
        return "puzzle", f"{spell(p.replace('Puzzle', '') for p in parts[1:] if not p.isdigit() and p != 'Puzzle')} puzzle"
    if parts[:3] == ["Challenge", "Standstone", "Adventure"]:     # the game's "Abyss Cresset" (secret place)
        return "abyss-cresset", "Abyss Cresset"
    if parts[0] == "Challenge" and len(parts) > 1:
        return "challenge", f"{spell(p for p in parts[1:] if not p.isdigit())} challenge"
    if parts[0] in ("FactionStructure", "Management") and len(parts) > 1:
        return "building", spell(parts[1:])
    if parts[0] == "Shop" and len(parts) > 1:
        rest = [p for p in parts[1:] if not p.isdigit()]
        if rest[:3] == ["Trader", "Street", "Trader"]:
            return "trader", "Street trader"
        cat, label = SHOP_KINDS.get(rest[0].lower(), ("shop", spell(rest[:1])))
        rest = [p for p in rest[1:] if p not in label.split()]  # Shop_<kind>_<town>[_Faction_<faction>]
        cut = rest.index("Faction") if "Faction" in rest else len(rest)
        town = spell(p for p in rest[:cut] if p != "Trader")
        faction = spell(rest[cut + 1:])
        where = f"{town} ({faction})" if town and faction else town or faction
        return cat, f"{label} · {where}" if where else label
    return None


def town_bells(archive, names):
    """The eight town bells as markers named "Bell"; the game's title for each goes in the notes."""
    out = []
    for level, entry in sorted(levels.levels(archive, BELL_LEVEL).items()):
        suffix = level[len(BELL_LEVEL):].lower()                 # "hernand", "scholastoneinstitute"
        town = next((t for t in BELL_TOWNS if suffix.startswith(t.lower())), None)
        pos = levels.centre(archive.read(entry))
        if town is None or pos is None:
            log.warning("bell level %s: no town or no position", level)
            continue
        title, _ = names.lookup(f"Knowledge_Pororin_Bell_{town}")
        out.append(_marker(f"{town}_Bell", "bell", "Bell", pos, title or f"Bell of {town}"))
    return out


def _realm(y):
    return "abyss" if y > ABYSS_Y else "pywel"


def _marker(mid, cat, name, pos, notes=None):
    x, y, z = pos
    m = {"id": mid, "category": cat, "name": name, "realm": _realm(y), "x": round(x, 2), "y": round(y, 2), "z": round(z, 2)}
    if notes:
        m["notes"] = notes[:500]
    return m


class Names:
    """English names and descriptions from knowledgeinfo rows (by row name) + knowledge.paloc."""

    def __init__(self, archive, lang="eng"):
        self.strings = load_strings(archive, "knowledge", lang)
        self.rows = {r.name: r for r in read_table(archive, "knowledgeinfo")} if self.strings else {}

    def lookup(self, row_name):
        row = self.rows.get(row_name)
        texts = texts_in(row.payload, self.strings) if row else []
        if not texts:
            return None, None
        return texts[0], (texts[1] if len(texts) > 1 and texts[1].rstrip(".") != texts[0] else None)


# Places at sea (DLC "Charting the Unknown"): islands, sunken ruins and sea caves. Their rows hold the
# position twice, then sizes that the on-land check can mistake for a position, so they take the
# earliest position at Pywel height instead; a leading field makes small numbers near (0, 0) look like
# one, so both x and z must be at least 300 m from 0. Node_Pywel_Ocean* are whole sea areas, not places.
SEA_PLACE = re.compile(r"^Node_(Ocean|Island|MayaRuins)_")
SEA_AREA = re.compile(r"^Node_Pywel_Ocean")


def _at_sea(x, y, z):
    return WORLD[0] < x < WORLD[2] and WORLD[1] < z < WORLD[3] and -100 < y <= ABYSS_Y and max(abs(x), abs(z)) > 300


def places(archive, ctx):
    markers, skipped, named = [], 0, 0
    for row in read_table(archive, "factionnode"):
        if not row.name.startswith("Node_") or SEA_AREA.match(row.name):
            continue
        if SEA_PLACE.match(row.name):
            pos = first_position(row.payload, _at_sea)
        else:
            pos = first_position(row.payload, *ctx["checks"])
        if pos is None:
            skipped += 1
            continue
        title, notes = ctx["names"].lookup("Knowledge_" + row.name)
        named += title is not None
        english = title if ctx["english"] is ctx["names"] else ctx["english"].lookup("Knowledge_" + row.name)[0]
        markers.append(_marker(row.name, place_category(row.name, english), title or place_name(row.name), pos, notes))
    ctx["places"] = markers
    log.info("places: %d markers (%d with game names), %d rows without a position", len(markers), named, skipped)
    cats = [{"id": c, "name": n, "group": group_of(c)} for c, n, _ in PLACE_RULES + [LANDMARK]] + \
        [{"id": OTHER_PLACE[0], "name": OTHER_PLACE[1], "group": group_of(OTHER_PLACE[0])}]
    return _set("game-places", "Places (game data)", archive, cats, markers)


def _revive_rows(archive, ctx):
    """[(marker id, category, position)]: 2.04 grouped points, else the 2.03 reviepointinfo rows."""
    try:
        types = {r.key: r.name for r in read_table(archive, "fieldreviveinfo")}
        groups = {}
        for blob in read_miscs(archive, "fieldreviveinfo_misc"):           # the base game's, then each DLC's
            for key, points in grouped_points(blob).items():
                groups.setdefault(key, []).extend(points)
    except ArchiveError:
        out = []
        for row in read_table(archive, "reviepointinfo"):
            rule = next((r for r in REVIVE_RULES if r[2].match(row.name)), None)
            pos = rule and first_position(row.payload, *ctx["checks"])
            if pos:
                out.append((row.name, rule[0], pos))
        return out
    out = []
    for key, points in groups.items():
        name = types.get(key, "")
        cat = next((c for c, rx in REVIVE_TYPES if rx.match(name)), None)
        for x, y, z in points if cat else ():
            if WORLD[0] < x < WORLD[2] and WORLD[1] < z < WORLD[3]:
                out.append((f"{name}@{x:.2f}:{z:.2f}", cat, (x, y, z)))
    return out


def revive_points(archive, ctx):
    markers, counters, labels = [], {}, {c: n.rstrip("s") for c, n, _ in REVIVE_RULES}
    for mid, cat, pos in _revive_rows(archive, ctx):
        counters[cat] = counters.get(cat, 0) + 1
        markers.append(_marker(mid, cat, f"{labels[cat]} {counters[cat]}", pos))
    log.info("revive points: %d markers", len(markers))
    cats = [{"id": c, "name": n, "group": group_of(c)} for c, n, _ in REVIVE_RULES]
    return _set("game-points", "Rest & Abyss points (game data)", archive, cats, markers)


def points_of_interest(archive, ctx):
    markers, ids, skipped = [], set(), 0
    for name, x, y, z in (p for blob in read_miscs(archive, "levelgimmicksceneobjectinfo_misc") for p in placements(blob)):
        kind = poi_kind(name)
        if kind is None:
            skipped += 1
            continue
        cat, label = kind
        notes = None
        if cat == "abyss-cresset":            # the game's own title and description
            title, notes = ctx["names"].lookup(CRESSET_KNOWLEDGE)
            label = title or label
        if cat == "abyss-gate":
            title, _ = ctx["names"].lookup(re.match(r"AbyssGate_\d+", name).group(0))
            label = title or label
        mid = name
        while mid in ids:
            mid += "+"
        ids.add(mid)
        markers.append(_marker(mid, cat, label, (x, y, z), notes))
    try:
        bells = town_bells(archive, ctx["names"])
    except Exception as e:       # bells are one category among many: log and carry on
        log.warning("town bells unreadable: %s", e)
        bells = []
    markers += bells
    log.info("bells: %d of %d town bells located: %s", len(bells), len(BELL_TOWNS), ", ".join(m["id"] for m in bells))
    log.info("points of interest: %d markers, %d other placed objects skipped", len(markers), skipped)
    cats = [{"id": c, "name": n, "group": group_of(c)} for c, n in POI_CATEGORIES]
    return _set("game-poi", "Points of interest (game data)", archive, cats, markers)


def resources(archive, ctx):
    """Objects placed by type: ore, plants, crafting stations, chests, memory fragments, ...
    The type is the gimmickinfo row; its English name comes from gimmick.paloc."""
    types = {r.key: r for r in read_table(archive, "gimmickinfo")}
    try:
        strings = load_strings(archive, "gimmick", ctx.get("lang", "eng"))
    except Exception as e:           # names are a nicety: fall back to the category names
        log.warning("gimmick names unavailable: %s", e)
        strings = {}
    labels = {cat: name for cat, name, _, _ in RESOURCE_RULES}
    names, markers, seen, skipped = {}, [], set(), 0
    for key, x, y, z in (p for blob in read_miscs(archive, "levelgimmicksceneobjectinfo_misc") for p in typed_placements(blob)):
        row = types.get(key)
        cat = row and resource_category(row.name)
        if not cat:
            skipped += 1
            continue
        mid = f"{row.name}@{x:.2f}:{z:.2f}"
        if mid in seen:                  # the same object listed twice (sector and content level)
            continue
        seen.add(mid)
        if key not in names:
            found = texts_in(row.payload, strings, 1) if strings else []
            names[key] = found[0] if found and "[EMPTY]" not in found[0] else singular(labels[cat])
        markers.append(_marker(mid, cat, names[key], (x, y, z)))
    counts = {}
    for m in markers:
        counts[m["category"]] = counts.get(m["category"], 0) + 1
    log.info("resources: %d markers (%s), %d other placed objects skipped", len(markers),
             ", ".join(f"{c} {n}" for c, n in sorted(counts.items())), skipped)
    # off by default: thousands of them would bury the map; the marker panel switches them on
    cats = [{"id": c, "name": n, "group": g, "off": True} for c, n, g, _ in RESOURCE_RULES]
    return _set("game-resources", "Resources & treasures (game data)", archive, cats, markers)


def animals(archive, ctx):
    """Spawn areas of the named wild species: nearby spawn points of one species become one marker."""
    def real(x, y, z):
        return not (abs(x - STAGE_PLACEHOLDER[0]) < 0.01 and abs(y - STAGE_PLACEHOLDER[1]) < 0.01)
    checks = [lambda *p, c=c: real(*p) and c(*p) for c in ctx["checks"]]
    areas = {}                                           # category -> [[sum x, sum y, sum z, count, name]]
    for row in read_table(archive, "stageinfo"):
        kind = animal_kind(row.name)
        pos = kind and first_position(row.payload, *checks)
        if not pos:
            continue
        cat, name = kind
        x, y, z = pos
        for a in areas.setdefault(cat, []):
            if math.hypot(a[0] / a[3] - x, a[2] / a[3] - z) <= HERD_M:
                a[0] += x; a[1] += y; a[2] += z; a[3] += 1
                break
        else:
            areas[cat].append([x, y, z, 1, name])
    markers = []
    for cat, found in areas.items():
        for i, (sx, sy, sz, n, name) in enumerate(found, 1):
            note = f"Spawn area ({n} spawn point{'s' if n > 1 else ''})"
            markers.append(_marker(f"{cat}-{i}", cat, name, (sx / n, sy / n, sz / n), note))
    log.info("animals: %d spawn areas (%s)", len(markers), ", ".join(f"{c} {len(v)}" for c, v in sorted(areas.items())))
    cats = [{"id": c, "name": n, "group": "Animals", "off": True} for c, n, _, _ in ANIMALS]
    return _set("game-animals", "Animals (game data)", archive, cats, markers)


def provinces(archive, ctx):
    """Province names as labels, placed deep inside each province; named after the places in them."""
    labels = regions.province_labels(archive, ctx.get("places", []))
    markers = [_marker("Region_" + name.replace(" ", ""), "region", name, (x, 0.0, z)) for name, x, z in labels]
    cats = [{"id": "region", "name": "Province names", "group": group_of("region")}]
    return _set("game-regions", "Regions (game data)", archive, cats, markers)


def _set(set_id, name, archive, categories, markers):
    used = {m["category"] for m in markers}
    return {"id": set_id, "name": name, "source": "A", "licence": LICENCE, "gameVersion": archive.version(),
            "categories": [c for c in categories if c["id"] in used], "markers": markers}


EXTRACTORS = (places, points_of_interest, revive_points, resources, animals, provinces)   # places first: provinces are named from them
COAST_SDF = 60       # land layer value: 128 is the coast, 60 is ~40 m out to sea (shipwrecks, piers)


def position_checks(archive):
    """Checks for tables.first_position, in order of preference:
    1. at Pywel height, on (or just off) land in the game's own land layer;
    2. at Abyss height, and not a round number (counters and sizes are; real positions aren't)."""
    found = worldmap.layer_set(archive)
    land = worldmap.load_layer(archive, "land", layers=found)
    size, px, (x0, _, x1, z1) = land.width, land.load(), found.world

    def on_land(x, y, z):
        u, v = int((x - x0) / (x1 - x0) * size), int((z1 - z) / (x1 - x0) * size)
        return y <= ABYSS_Y and 0 <= u < size and 0 <= v < size and px[u, v] > COAST_SDF

    def in_abyss(x, y, z):
        return y > ABYSS_Y and ((x * 4) % 1 or (z * 4) % 1)
    return on_land, in_abyss


def import_markers(archive, store, lang="eng"):
    """Extract every marker set and save it (replacing the previous game import). `lang` is the game
    language for the names the game itself gives (places, resources); our own labels stay English.
    Returns (summaries, failures); a table that cannot be read is logged and skipped."""
    summaries, failures = [], []
    try:
        with timed("markers: names"):
            names = Names(archive, lang)
    except Exception as e:          # names are a nicety: carry on with internal names
        log.warning("game names unavailable: %s", e)
        failures.append(f"names: {e}")
        names = Names.__new__(Names)
        names.strings, names.rows = {}, {}
    english = names                # places are sorted into categories by their English name, whatever language is shown
    if lang != "eng" and names.strings:
        try:
            english = Names(archive, "eng")
        except Exception as e:
            log.warning("English names unavailable: %s", e)
    elif lang != "eng":
        log.warning("no '%s' string tables in this install: names stay as in the game files", lang)
        failures.append(f"names: language {lang} not found")
    with timed("markers: land layer"):
        ctx = {"checks": position_checks(archive), "names": names, "english": english, "lang": lang}
    built = []
    for extract in EXTRACTORS:
        try:
            with timed(f"markers: {extract.__name__}"):
                built.append(extract(archive, ctx))
        except Exception as e:   # one broken table must not stop the import
            log.warning("marker set %s failed: %s", extract.__name__, e)
            failures.append(f"{extract.__name__}: {e}")
    try:                         # the province each Pywel marker lies in, for the progress per province
        with timed("markers: province of each marker"):
            province = regions.province_lookup(archive, ctx.get("places", []))
            for data in built:
                for m in data["markers"] if data["id"] != "game-regions" else ():
                    name = province(m["x"], m["z"]) if m["realm"] == "pywel" else None
                    if name:
                        m["province"] = name
    except Exception as e:
        log.warning("provinces of the markers unavailable: %s", e)
        failures.append(f"provinces: {e}")
    for data in built:
        try:
            summary, carried, dropped = store.replace_set(data)
            summaries.append(summary)
            if carried or dropped:
                log.info("%s: %d found ticks followed objects that moved, %d belong to objects that are gone", data["id"], carried, dropped)
        except Exception as e:
            log.warning("marker set %s not saved: %s", data.get("id"), e)
            failures.append(f"{data.get('id')}: {e}")
    try:                         # the game's own icons; without them the shell keeps its own glyphs
        with timed("markers: icons"):
            png, cells, _ = icons.extract(archive)
            store.save_icons(png, cells, archive.version())
    except Exception as e:
        log.warning("game icons failed: %s", e)
        failures.append(f"icons: {e}")
    return summaries, failures
