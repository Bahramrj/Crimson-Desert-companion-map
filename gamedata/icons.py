"""The game's own map icons for our marker categories, cut from the UI icon atlases of the install.

The atlases are `ui/texture/cd_icon_{map,worldmap,knowledge}_NN.dds`, described by
`ui/xml/texture/<same name>.xml` (`<Texture Name=".." Filename=".." GetRect="x,y,w,h"/>`). Each
category below names the game icons that fit it, best first; the first one the install has wins.
Icons become white pictograms (luminance as alpha, which also drops the dark discs some shop icons
carry), fitted into square cells of one sprite sheet. The shell draws them on the category's own
coloured disc; categories without a game icon keep our own glyphs.

Nothing here writes files: `extract` returns the sheet, mapstore stores it in the user's data folder
(it is never committed or bundled).
"""

import io
import logging
import re

from PIL import Image

log = logging.getLogger("cdlivemap.gamedata.icons")

ATLAS_XML = re.compile(r"^ui/xml/texture/cd_icon_(map|worldmap|knowledge)_\d+\.xml$")
RECT = re.compile(r'<Texture\s+Name="([^"]+)"\s+Filename="([^"]+)"[^>]*?GetRect="(\d+),(\d+),(\d+),(\d+)"')
CELL = 64          # px per icon in the sheet
PAD = 3            # px kept free around each icon
COLUMNS = 16

K = "cd_icon_knowledge_category_"
ICONS = {
    # places
    "rest": ("cd_Icon_map_gimmick_campfire_00",),
    "gate": (K + "21", "cd_Icon_map_gimmick_stonegate_00"),
    "castle": (K + "56",),
    "trade": ("cd_icon_map_trade_small1", "cd_icon_map_trade_small"),
    "fort": (K + "18",),
    "camp": ("cd_icon_common_quest_camp_00",),
    "cave": (K + "20",),
    "ruins": (K + "19",),
    "temple": ("cd_Icon_map_church",),
    "fishing": (K + "05", "cd_Icon_map_fishing_point"),
    "village": ("cd_icon_map_village",),
    "work": (K + "67",),
    "house": (K + "70",),
    "landmark": (K + "12",),
    "place": (K + "66",),
    # points of interest
    "abyss-gate": ("cd_Icon_map_abyssgate",),
    "abyss-ruins": ("cd_Icon_map_gimmick_abyss_mark",),
    "abyss-cresset": ("cd_Icon_map_standstone",),
    "puzzle": (K + "47",),
    "challenge": (K + "03",),
    "bell": ("cd_Icon_map_gimmick_bell_00",),
    "blacksmith": ("cd_icon_map_blacksmith",),
    "inn": ("cd_Icon_map_inn",),
    "stable": ("cd_icon_map_stable",),
    "seed": ("cd_icon_map_seed",),
    "goods": ("cd_Icon_map_generalshop",),
    "trader": ("cd_icon_map_trade",),
    "wanted": ("cd_Icon_map_wanted_NHM_00",),
    "bank": ("cd_icon_map_bank",),
    "shop": ("cd_icon_map_merchant_shop",),
    "building": ("cd_Icon_map_node_sub_inner_barracks",),
    # rest points
    "meditation": (K + "59", "cd_Icon_map_placeofprayer"),
    "rest-point": ("cd_Icon_map_GimmickFlag",),
    "abyss-bridge": ("cd_icon_map_gimmick_abyssone_bridge_gate",),
    # resources
    "ore-iron": ("cd_Icon_map_gimmick_IronStone_00",),
    "ore-copper": ("cd_Icon_map_gimmick_CopperOre_00",),
    "ore-silver": ("cd_Icon_map_gimmick_minesilver_00",),
    "ore-gold": ("cd_Icon_map_gimmick_minegold_00",),
    "ore-bismuth": ("cd_Icon_map_gimmick_BismuthOre_00",),
    "ore-diamond": ("cd_Icon_map_gimmick_diamond_00",),
    "ore-garnet": ("cd_Icon_map_gimmick_Ruby_00",),
    "ore-azurite": ("cd_Icon_map_gimmick_BlueStone_00",),
    "ore-bloodstone": ("cd_Icon_map_gimmick_redstone_00",),
    "ore-epidote": ("cd_Icon_map_gimmick_GreenStone_00",),
    "ore-scolecite": ("cd_Icon_map_gimmick_WhiteStone_00",),
    "ore-brimstone": ("cd_Icon_map_gimmick_SulfurStone_00",),
    "ore-manganese": ("cd_Icon_map_gimmick_Manganese_00",),
    "ore-quartz": ("cd_Icon_map_gimmick_Quartz_00",),
    "ore-malachite": ("cd_Icon_map_gimmick_Malachite_00",),
    "ore-hydrothermal": ("cd_Icon_map_gimmick_hydrothermalmineral_00",),
    "ore-obsidian": ("cd_Icon_map_gimmick_Obsidian_00",),
    "plant-palmar": ("cd_Icon_map_gimmick_jijeongta_leaf_00",),
    "plant-taro": ("cd_Icon_map_gimmick_taro_00",),
    "plant-amaranth": ("cd_Icon_map_gimmick_amaranth_00",),
    "plant-seaweed": ("cd_Icon_map_gimmick_dulse_00",),
    "plant-chaya": ("cd_Icon_map_gimmick_chaya_00",),
    "plant-prickly-pear": ("cd_Icon_map_gimmick_opuntia_00",),
    "plant-enset": ("cd_Icon_map_gimmick_ensete_00",),
    "plant-algae": ("cd_Icon_map_gimmick_chlorella_00",),
    "plant-skyroot": ("cd_Icon_map_gimmick_Kudzu_Vine_00",),
    "plant-rubber": ("cd_Icon_map_gimmick_Rubber_00",),
    "mercury": ("cd_Icon_map_gimmick_Mercury_00",),
    "sea-coral": ("cd_Icon_map_gimmick_goldencoral_00",),
    "sea-fan-coral": ("cd_Icon_map_gimmick_blackcoral_00",),
    "sea-reef": ("cd_Icon_map_gimmick_searock_001",),
    "sea-pearl": ("cd_Icon_map_gimmick_Natural_Pearl_00",),
    "sea-ambergris": ("cd_Icon_map_gimmick_ambergris_00",),
    "craft-bonfire": ("cd_Icon_map_gimmick_campfire_00",),
    "craft-cooking": ("cd_Icon_map_gimmick_craft_cook_oven_00",),
    "craft-anvil": ("cd_Icon_map_gimmick_craft_anvil_00",),
    "craft-grindstone": ("cd_Icon_map_gimmick_blacksmithstone_00",),
    "craft-forge": (K + "30",),
    "craft-cauldron": ("cd_icon_map_gimmick_craft_medicine",),
    "craft-loom": ("cd_Icon_map_gimmick_sewing_00",),
    "craft-workstation": ("cd_Icon_map_gimmick_carpentry_00",),
    "well": ("cd_icon_map_gimmick_well_00",),
    "chest": ("cd_Icon_map_treasurebox",),
    "small-box": ("cd_Icon_map_gimmick_box_00",),
    "boss-fragment": ("cd_icon_map_visione_memory_chip_boss",),
    "memory-fragment": ("cd_icon_map_visione_memory_chip",),
    "sealed-artifact": ("cd_Icon_map_artifact_sealed_00",),
    "equipment": ("cd_icon_map_item_abyssgear",),
    "donation": ("cd_Icon_map_resource_money_item",),
    "totem": ("cd_icon_map_witch",),
    "arcade": (K + "43",),
    "facility": ("cd_Icon_map_subinner_normal",),
    "repair-shop": ("cd_Icon_map_gimmick_ATAG_tunnel",),
    "house-site": (K + "70",),
    "transporter": ("cd_icon_map_gimmick_marni_teleportation",),
    "dock": ("cd_icon_map_ship_anchor",),
    "business": ("cd_icon_map_managemant_00",),
    # animals (no game icon for rhinos, elephants, butterflies and fireflies)
    "animal-boar": ("cd_Icon_map_Warthog",),
    "animal-bison": ("cd_icon_map_Bison",),
    "animal-eagle": ("cd_icon_map_pet_Hawk", "cd_icon_map_bird"),
    "animal-gazelle": ("cd_Icon_map_Deer",),
    "animal-deer": ("cd_Icon_map_Deer",),
    "animal-goat": ("cd_icon_map_sheep",),
    "animal-ibex": ("cd_Icon_map_AlpineIbex",),
    "animal-komodo": ("cd_Icon_map_Iguana",),
    "animal-turtle": ("cd_icon_map_Turtle",),
    "animal-camel": ("cd_Icon_map_Camel",),
    "animal-bear": ("cd_Icon_map_Bear",),
    "animal-flamingo": ("cd_icon_map_bird",),
}


UI_GROUP = "0012"            # the UI textures and their atlas descriptions (also the world-map layers)


def _find(archive, pattern):
    """Entries matching `pattern` in the UI group; only if it has none, in every group (a patch may move
    them). Looking in every group first would index all two million files of the install."""
    found = archive.find(pattern, [UI_GROUP]) if UI_GROUP in archive.groups() else []
    return found or archive.find(pattern)


def atlas_rects(archive):
    """{icon name (lower case): (texture path, (x, y, w, h))} from every icon atlas description."""
    rects = {}
    for entry in _find(archive, "ui/xml/texture/cd_icon_*.xml"):
        if not ATLAS_XML.match(entry.path.lower()):
            continue
        text = archive.read(entry).decode("utf-8", "replace")
        for m in RECT.finditer(text):
            rects.setdefault(m.group(1).lower(), (m.group(2).lower(), tuple(int(v) for v in m.groups()[2:])))
    return rects


def pictogram(icon):
    """White pictogram: luminance becomes alpha, so shading stays and dark backgrounds go; trimmed and
    fitted into a CELL x CELL square (centred, PAD free)."""
    icon = icon.convert("RGBA")
    lum = icon.convert("L").point(lambda v: max(0, min(255, (v - 70) * 255 // 150)))
    alpha = Image.composite(lum, Image.new("L", icon.size, 0), icon.getchannel("A"))
    bbox = alpha.point(lambda v: 255 if v > 24 else 0).getbbox()
    if bbox is None:
        return None
    alpha = alpha.crop(bbox)
    side = CELL - 2 * PAD
    scale = min(side / alpha.width, side / alpha.height)
    alpha = alpha.resize((max(1, round(alpha.width * scale)), max(1, round(alpha.height * scale))), Image.LANCZOS)
    out = Image.new("RGBA", (CELL, CELL), (255, 255, 255, 0))
    white = Image.new("RGBA", alpha.size, (255, 255, 255, 255))
    white.putalpha(alpha)
    out.alpha_composite(white, ((CELL - alpha.width) // 2, (CELL - alpha.height) // 2))
    return out


def extract(archive, wanted=ICONS):
    """(sheet PNG bytes, {category: [x, y, w, h]}, [categories without a game icon]).
    Unreadable atlases are logged and skipped; with none at all the sheet is None."""
    rects = atlas_rects(archive)
    textures, cells, missing = {}, {}, []
    entries = {e.path.lower(): e for e in _find(archive, "ui/texture/cd_icon_*.dds")}
    for category, names in wanted.items():
        found = next((rects[n.lower()] for n in names if n.lower() in rects), None)
        if found is None:
            missing.append(category)
            continue
        path, (x, y, w, h) = found
        if path not in textures:
            try:
                entry = entries.get(path)
                textures[path] = Image.open(io.BytesIO(archive.read(entry))).convert("RGBA") if entry else None
            except Exception as e:      # one broken atlas must not stop the others
                log.warning("icon atlas %s unreadable: %s", path, e)
                textures[path] = None
        atlas = textures[path]
        icon = pictogram(atlas.crop((x, y, x + w, y + h))) if atlas is not None else None
        if icon is None:
            missing.append(category)
            continue
        cells[category] = icon
    log.info("game icons: %d categories, %d without a game icon (%s)", len(cells), len(missing), ", ".join(missing))
    if not cells:
        return None, {}, missing
    rows = (len(cells) + COLUMNS - 1) // COLUMNS
    sheet = Image.new("RGBA", (COLUMNS * CELL, rows * CELL), (255, 255, 255, 0))
    index = {}
    for i, (category, icon) in enumerate(sorted(cells.items())):
        x, y = (i % COLUMNS) * CELL, (i // COLUMNS) * CELL
        sheet.alpha_composite(icon, (x, y))
        index[category] = [x, y, CELL, CELL]
    buf = io.BytesIO()
    sheet.save(buf, "PNG", optimize=True)
    return buf.getvalue(), index, missing
