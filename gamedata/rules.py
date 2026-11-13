"""The rules that turn the game's internal names into marker categories: data, no code.

After a game update this is the file to edit: a new kind of place, shop, ore or
animal is one more row here. gamedata/markers.py applies the rules.
- PLACE_RULES / LANDMARK / CRAFT_WORDS: category of a place from the words of its name; first match wins.
- SHOP_KINDS: shop kind (lower case) -> (category, label).   - GROUPS: category -> panel group.
- RESOURCE_RULES: (category, name, panel group, pattern on the gimmickinfo row name); first match wins.
- REVIVE_RULES / REVIVE_TYPES: rest points up to 2.03 / from 2.04.   - ANIMALS: (category, name, marker name, pattern).
"""

import re

BELL_TOWNS = ("Hernand", "Pailune", "Calphade", "Tashkalp", "Demeniss", "Delesyia", "Scholastone", "Varnia")

REGIONS = {"Her": "Hernand", "Dem": "Demeniss", "Del": "Delesyia", "Kwe": "Kweiden", "Crim": "Crimson Desert",
           "CD": "Crimson Desert", "Cal": "Calphade", "AbyssIsland": "Abyss", "HyperSpace": "Hyperspace"}

# first matching rule wins; keywords are words of the internal name, then of the English name
PLACE_RULES = [
    ("rest", "Rest areas", ("RestArea",)),
    ("gate", "Gates", ("Gate",)),
    ("castle", "Castles & manors", ("Castle", "Manor", "Palace", "Keep")),
    ("trade", "Trading posts & markets", ("Trading", "Market", "Marketplace", "Guildhouse", "Bazaar", "Exchange", "Tradehouse")),
    ("fort", "Forts & watchtowers", ("Fort", "Fortress", "Outpost", "Watchtower", "Tower", "Beacon", "Post", "Watch",
                                     "Garrison", "Barracks", "Stronghold", "Armory", "Training")),
    ("camp", "Camps & hideouts", ("Camp", "Hideout", "Den", "Lair")),
    ("cave", "Caves", ("Cave", "Cavern", "Grotto", "Hollow")),
    ("ruins", "Ruins & tombs", ("Ruins", "Ruin", "Shipwreck", "Wreck", "Abandoned", "Tomb", "Graves", "Grave", "Cemetery",
                                "Crypt", "Dig")),
    ("temple", "Temples & churches", ("Temple", "Sanctum", "Shrine", "Sanctuary", "Chapel", "Altar", "Church", "Cathedral",
                                      "Abbey", "Monastery")),
    ("fishing", "Fishing spots", ("Fishing", "Fisher", "Fishers")),
    ("village", "Villages & towns", ("Village", "Town", "City", "Harbor", "Harbour", "Port", "Hamlet")),
    ("work", "Farms, mines & workshops", ("Farm", "Ranch", "Mill", "Sawmill", "Quarry", "Mine", "Factory", "Workshop",
                                          "Saddlery", "Smithy", "Dock", "Fishing", "Vineyard", "Orchard", "Station")),
    ("house", "Houses & cabins", ("Cabin", "House", "Hut", "Lodge", "Inn", "Housing", "Residence")),
]

# craftsmen and works named by their trade ("Warspike Spearmaker", "Totesmith Tannery")
CRAFT_WORDS = ("maker", "makers", "smith", "craftshop", "works", "tannery", "dyehouse", "bindery", "mappery", "apothecary",
               "depot", "storage", "pasture", "winery", "plantation", "foundry", "scrapyard", "warehouse", "pottery",
               "farmhouse")

LANDMARK = ("landmark", "Landmarks", ("Lake", "Oasis", "Forest", "Woods", "Gorge", "Pass", "Rock", "Rocks", "Tree", "Eldertree",
                                      "Valley", "Canyon", "Falls", "Waterfall", "Peak", "Hill", "Cliff", "Cliffs", "Spring",
                                      "Springs", "Bridge", "Island", "Nest", "Grove", "Marsh", "Swamp", "Dunes", "Wetlands",
                                      "Isle", "Isles", "Islet", "Reef", "Lagoon", "Cove", "Bay", "Atoll", "Rapids", "Coast"))

OTHER_PLACE = ("place", "Other places")

# The Abyss artifact ruins in this table are the same objects as AbyssRuins_* placements (0 m apart),
# which carry better names, so they come from the points-of-interest set instead.
REVIVE_RULES = [
    ("meditation", "Meditation spots", re.compile(r"^gimmick_revivepoint_meditation", re.I)),
    ("rest-point", "Rest points", re.compile(r"^gimmick_revivepoint_", re.I)),
    ("abyss-bridge", "Abyss bridge gates", re.compile(r"^gimmick_abyssone_bridge_gate", re.I)),
]

# From 2.04 the points are grouped by type (fieldreviveinfo rows RevivePoint_<type>, positions in
# fieldreviveinfo_misc); first matching rule wins, None skips the type.
REVIVE_TYPES = [
    ("meditation", re.compile(r"^RevivePoint_Meditation", re.I)),
    ("abyss-bridge", re.compile(r"^RevivePoint_AbyssBridge", re.I)),
    (None, re.compile(r"^RevivePoint_AbyssRuins", re.I)),
    ("rest-point", re.compile(r"^RevivePoint_", re.I)),
]

# shop kind (lower case) -> (category, label)
SHOP_KINDS = {
    "smith": ("blacksmith", "Blacksmith"), "craftingblacksmith": ("blacksmith", "Crafting blacksmith"),
    "smithy": ("blacksmith", "Smithy"), "inn": ("inn", "Inn"),
    "stable": ("stable", "Stable"), "horsetool": ("stable", "Saddler"), "horsefence": ("stable", "Horse dealer"),
    "wagon": ("stable", "Wagon maker"), "carriage": ("stable", "Carriages"), "carriagefence": ("trader", "Carriage fence"),
    "seatdealer": ("seed", "Seed dealer"),
    "general": ("goods", "General store"), "grocery": ("goods", "Grocer"), "butcher": ("goods", "Butcher"),
    "cook": ("goods", "Cook"), "lanch": ("goods", "Lunch"), "food": ("goods", "Food trader"),
    "farmer": ("goods", "Farmer"), "supplies": ("goods", "Supplies"),
    "trader": ("trader", "Trader"), "blackmarket": ("trader", "Black market"), "smuggler": ("trader", "Smuggler"),
    "goldleafguildhouse": ("trader", "Goldleaf Guildhouse"), "redwindtradingassociation": ("trader", "Red Wind trader"),
    "silvermoontroll": ("trader", "Silvermoon trader"), "mineral": ("trader", "Mineral trader"),
    "timber": ("trader", "Timber trader"), "domesticfence": ("trader", "Fence"),
    "wanted": ("wanted", "Wanted board"), "relic": ("trader", "Relic Collector"),
    "bank": ("bank", "Bank"), "coin": ("bank", "Coin exchange"), "bond": ("bank", "Bonds"), "warehouse": ("bank", "Warehouse"),
}

# Panel groups (like the sections of online map sites): category id -> group
GROUPS = {
    "rest": "Rest & travel", "meditation": "Rest & travel", "rest-point": "Rest & travel",
    "abyss-gate": "Abyss", "abyss-ruins": "Abyss", "abyss-bridge": "Abyss", "bell": "Abyss",
    "puzzle": "Activities", "challenge": "Activities", "region": "Regions", "fishing": "Activities", "trade": "Services",
    "abyss-cresset": "Abyss",
    "blacksmith": "Services", "inn": "Services", "stable": "Services", "seed": "Services", "goods": "Services",
    "trader": "Services", "wanted": "Services", "bank": "Services", "shop": "Services",
}

# Objects placed by type (tables.typed_placements), matched on their gimmickinfo row name; first match wins.
# (category, category name, panel group, rule). Names on the map are the game's own (gimmick.paloc).
# Shop tables, Abyss gates / nexuses / bridge gates and management posts are left out: the other sets
# already have them, with better names.
RESOURCE_RULES = [
    ("ore-iron", "Iron", "Mining", r"mine_iron"), ("ore-copper", "Copper", "Mining", r"mine_copper"),
    ("ore-silver", "Silver", "Mining", r"mine_silver"), ("ore-gold", "Gold", "Mining", r"mine_gold"),
    ("ore-bismuth", "Bismuth", "Mining", r"mine_bismuth"), ("ore-diamond", "Diamond", "Mining", r"mine_diamond"),
    ("ore-garnet", "Garnet", "Mining", r"mine_ruby"), ("ore-azurite", "Azurite", "Mining", r"mine_bluestone"),
    ("ore-bloodstone", "Bloodstone", "Mining", r"mine_redstone"), ("ore-epidote", "Epidote", "Mining", r"mine_greenstone"),
    ("ore-scolecite", "Scolecite", "Mining", r"mine_whitestone"), ("ore-brimstone", "Brimstone", "Mining", r"gimmick_sulfur_rock"),
    ("ore-manganese", "Manganese nodules", "Mining", r"mine_manganese"), ("ore-quartz", "Shiny minerals", "Mining", r"mine_quartz"),
    ("ore-malachite", "Malachite", "Mining", r"mine_malachite"),
    ("ore-hydrothermal", "Hydrothermal deposits", "Mining", r"mine_hydrothermalmineral"),
    ("ore-obsidian", "Obsidian", "Mining", r"gimmick_mine_obsidian"),
    ("plant-palmar", "Palmar leaves", "Gathering", r"gimmick_jijeongta_leaf"), ("plant-taro", "Taro", "Gathering", r"taro_"),
    ("plant-amaranth", "Amaranth", "Gathering", r"amaranth_"), ("plant-seaweed", "Red seaweed", "Gathering", r"dulse_"),
    ("plant-chaya", "Chaya", "Gathering", r"chaya_"), ("plant-prickly-pear", "Prickly pears", "Gathering", r"opuntia_"),
    ("plant-enset", "Enset", "Gathering", r"ensete_"), ("plant-algae", "Green algae", "Gathering", r"chlorella_"),
    ("plant-skyroot", "Skyroot vines", "Gathering", r"gimmick_kudzu_vine"), ("plant-rubber", "Rubber", "Gathering", r"rare_collect_rubber"),
    ("mercury", "Mercury pools", "Gathering", r"gimmick_waterpool"),
    ("sea-coral", "Golden coral", "Gathering", r"goldencoral"), ("sea-fan-coral", "Sea fan coral", "Gathering", r"blackcoral"),
    ("sea-reef", "Reefs", "Gathering", r"searock_"), ("sea-pearl", "Natural pearls", "Gathering", r"gimmick_pearl"),
    ("sea-ambergris", "Ambergris", "Gathering", r"mine_ambergris"),
    ("craft-bonfire", "Bonfires", "Crafting", r"gimmick_craft_cook_campfire"),
    ("craft-cooking", "Special cooking tools", "Crafting", r"gimmick_craft_cook_oven"),
    ("craft-anvil", "Anvils", "Crafting", r"gimmick_craft_anvil"), ("craft-grindstone", "Grindstones", "Crafting", r"gimmick_tool_blacksmithstone"),
    ("craft-forge", "Forges", "Crafting", r"craft_smith_"), ("craft-cauldron", "Cauldrons", "Crafting", r"craft_medicine_"),
    ("craft-loom", "Looms", "Crafting", r"craft_sewing_"), ("craft-workstation", "Workstations", "Crafting", r"carpenter_"),
    ("well", "Wells", "Crafting", r"gimmick_well_"),
    ("chest", "Treasure chests", "Treasures", r"itembox_|temple_chest_|safebox_|dff_chest_"),
    ("small-box", "Small boxes", "Treasures", r"gimmick_item_dropset_treasurebox"),
    ("boss-fragment", "Boss memory fragments", "Treasures", r"item_visione_chip_bossrematch"),
    ("memory-fragment", "Memory fragments", "Treasures", r"item_visione_chip"),
    ("sealed-artifact", "Sealed Abyss artifacts", "Treasures", r"item_sealed_artifact"),
    ("equipment", "Equipment", "Treasures", r"gimmick_equip_|item_basic_|item_spear_equip"),
    ("donation", "Donation boxes", "Activities", r"gimmick_action_donation"),
    ("totem", "Witch totems", "Activities", r"hexe_tower"),
    ("arcade", "Arcade machines", "Activities", r"pinballmachine|clawmachine|cushionballmachine"),
    ("facility", "Camp facilities", "Locations", r"gimmick_subinner_"),
    ("repair-shop", "A.T.A.G. repair shops", "Locations", r"gimmick_middle_tunnel"),
    ("house-site", "House sites", "Rest & travel", r"gimmick_housing_movepoint"),
    ("transporter", "Transporters", "Rest & travel", r"gimmick_marni_teleportation"),
    ("dock", "Anchorages", "Rest & travel", r"gimmick_ship_foothold_dock"),
    ("business", "Businesses for rent", "Services", r"management_node_"),
]

ANIMALS = [   # (category, category name, marker name, kind pattern)
    ("animal-boar", "Boars", "Boar", r"land_boar"), ("animal-bison", "Bison", "Bison", r"land_bison"),
    ("animal-eagle", "Eagles", "Eagle", r"land_eagle"), ("animal-gazelle", "Gazelles", "Gazelle", r"land_gazelle"),
    ("animal-deer", "Pronghorn deer", "Pronghorn deer", r"land_pronghorndeer"),
    ("animal-goat", "Goats & sheep", "Goats & sheep", r"land_goat"),
    ("animal-ibex", "Alpine ibex", "Alpine ibex", r"land_alpineibex"),
    ("animal-komodo", "Komodo dragons", "Komodo dragon", r"land_komododragon"),
    ("animal-rhino", "Rhinos", "Rhino", r"land_rhino"), ("animal-turtle", "Turtles", "Turtle", r"land_turtle"),
    ("animal-camel", "Camels", "Camel", r"land_camel"), ("animal-bear", "Bears", "Bear", r"land_bear"),
    ("animal-elephant", "Elephants", "Elephant", r"land_elephant"),
    ("animal-flamingo", "Flamingos", "Flamingo", r"waterside_flamingo"),
    ("animal-butterfly", "Butterflies", "Butterflies", r"pof_butterfly"), ("animal-firefly", "Fireflies", "Fireflies", r"land_firefly"),
]

POI_CATEGORIES = [
    ("abyss-gate", "Abyss gates"), ("abyss-ruins", "Abyss ruins"), ("abyss-cresset", "Abyss Cressets (secret places)"),
    ("puzzle", "Puzzles"), ("challenge", "Challenges"),
    ("bell", "Bells"), ("blacksmith", "Blacksmiths"), ("inn", "Inns"), ("stable", "Stables & wagons"),
    ("seed", "Seed dealers"), ("goods", "General stores & food"), ("trader", "Traders & black markets"),
    ("wanted", "Wanted boards"), ("bank", "Banks & storage"), ("shop", "Other shops"), ("building", "Faction buildings"),
]
