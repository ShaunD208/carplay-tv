#!/usr/bin/env python3
"""CarPlay TV v4 category normalizer.

Runs after build_playlist.py. Preserves the v3 playlist/fallback architecture while
normalizing display groups into the 21-category CarPlay taxonomy. Original provider
categories remain in channel_sources.json. Rules intentionally prefer useful provider
metadata first, then conservative channel-name inference.
"""

import json
import re
from collections import Counter
from pathlib import Path

MASTER = Path("master.m3u")
SOURCES = Path("channel_sources.json")
REPORT = Path("playlist_report.txt")

CATEGORIES = [
    "News", "Local News", "Sports", "Movies", "TV", "Comedy", "Crime",
    "Reality", "Classics", "Sci-Fi & Horror", "Kids", "Music", "Food & Home",
    "Lifestyle", "Nature & Travel", "History & Science", "Documentary", "Anime",
    "Game Shows", "Westerns", "Other",
]

ALIASES = {
    "local news": "Local News",
    "weather": "News",
    "news": "News", "national news": "News", "news & opinion": "News", "news + opinion": "News",
    "sports": "Sports", "sports & outdoors": "Sports", "sports on now": "Sports",
    "motor sports": "Sports", "motorsports": "Sports", "pro wrestling": "Sports",
    "games & competition": "Reality",
    "movies": "Movies", "movie": "Movies", "romance": "TV",
    "tv & entertainment": "TV", "entertainment": "TV", "action & drama": "TV", "drama": "TV",
    "hit tv": "TV", "daytime tv": "TV", "daytime": "TV", "mystery": "Crime",
    "comedy": "Comedy",
    "crime": "Crime", "true crime": "Crime",
    "reality": "Reality", "reality tv": "Reality", "reality competition": "Reality",
    "competition reality": "Reality", "big brother live": "Reality",
    "classic tv": "Classics", "classics": "Classics", "western & classic tv": "Classics",
    "sci-fi": "Sci-Fi & Horror", "sci-fi & horror": "Sci-Fi & Horror",
    "horror": "Sci-Fi & Horror", "chills & thrills": "Sci-Fi & Horror",
    "kids": "Kids", "kids & family": "Kids", "animated": "Kids", "faith & family": "Lifestyle",
    "music": "Music", "music videos": "Music",
    "home & food": "Food & Home", "home + food": "Food & Home", "food & home": "Food & Home",
    "cooking": "Food & Home", "good eats": "Food & Home", "home improvement": "Food & Home",
    "lifestyle": "Lifestyle", "lifestyle & pop culture": "Lifestyle", "pop culture": "Lifestyle",
    "health": "Lifestyle", "auction": "Lifestyle",
    "animals": "Nature & Travel", "animals + nature": "Nature & Travel", "science & nature": "Nature & Travel",
    "environment": "Nature & Travel", "nature & travel": "Nature & Travel", "travel": "Nature & Travel",
    "nature, history & science": "History & Science", "history + science": "History & Science",
    "history & science": "History & Science", "educational": "History & Science", "gaming & tech": "History & Science",
    "documentary": "Documentary", "documentaries": "Documentary",
    "anime": "Anime", "anime & gaming": "Anime", "anime+": "Anime",
    "game shows": "Game Shows", "daytime + game shows": "Game Shows",
    "westerns": "Westerns", "western": "Westerns",
    "ambiance": "Lifestyle",
}

# Exact overrides are used only where the audit exposed well-known channels whose
# names do not contain enough generic words for a reliable regex classification.
EXACT = {
    "dora tv": "Kids", "like nastya": "Kids", "ninja kidz tv": "Kids",
    "garfield": "Kids", "pitufo tv": "Kids", "super mario brothers": "Kids",
    "beyblade": "Kids", "pink panther": "Kids", "the wiggles": "Kids",
    "mr. bean": "Comedy", "mr. bean live action": "Comedy", "corner gas": "Comedy",
    "green acres": "Classics", "dick van dyke": "Classics", "that girl": "Classics",
    "farscape": "Sci-Fi & Horror", "continuum": "Sci-Fi & Horror", "stargate by mgm": "Sci-Fi & Horror",
    "the outer limits": "Sci-Fi & Horror", "the outpost": "Sci-Fi & Horror",
    "dateline": "Crime", "prime suspect": "Crime", "silent witness|new tricks": "Crime",
    "silent witness and new tricks": "Crime", "on patrol: live": "Crime", "women behind bars": "Crime",
    "judge judy": "TV", "judge faith": "TV", "dr. phil": "TV", "wendy williams": "TV",
    "the bold and the beautiful": "TV", "mi-5": "TV", "rookie blue": "TV", "scandal": "TV",
    "nip/tuck": "TV", "mcLeods daughters": "TV", "love thy neighbor": "TV",
    "dance moms by lifetime": "Reality", "duck dynasty by a&e": "Reality", "the osbournes": "Reality",
    "say yes to the dress": "Reality", "love after lockup we tv": "Reality", "four in a bed": "Reality",
    "come dine with me": "Reality", "american gladiators by mgm": "Reality", "hard knocks": "Reality",
    "the biggest loser": "Reality", "fear factor usa": "Reality",
    "france 24": "News", "weathernation": "News", "local now charlotte": "Local News",
    "wsoc channel 9": "Local News", "very carolina by wxii": "Local News", "very carolina by wyff 4": "Local News",
    "the repair shop": "Food & Home", "property brothers channel": "Food & Home",
    "the great british baking channel": "Food & Home", "the emeril lagasse channel": "Food & Home",
    "great british menu": "Food & Home", "gordon ramsay": "Food & Home", "so yummy": "Food & Home",
    "bizarre foods with andrew zimmern": "Food & Home",
    "easy listening": "Music", "smooth jazz": "Music", "today's k-pop": "Music", "qwest tv": "Music",
    "classic rock": "Music", "hip-hop/r&b": "Music", "euro hits": "Music", "metal.rocks": "Music",
    "world surf league 24/7": "Sports", "unbeaten": "Sports", "fight network": "Sports",
    "glory kickboxing": "Sports", "strongman champions": "Sports", "acl cornhole tv": "Sports",
    "bowling tv": "Sports", "cricket gold": "Sports", "speed sport 1": "Sports", "speedvision": "Sports",
    "wired2fish": "Sports", "pickletv": "Sports", "swac tv": "Sports",
    "earthxtra": "Nature & Travel", "real wild": "Nature & Travel", "go wild": "Nature & Travel",
    "gotraveler": "Nature & Travel", "journy": "Nature & Travel", "the wicked tuna channel": "Nature & Travel",
    "cesar's pack leader tv": "Nature & Travel", "dog whisperer with cesar millan": "Nature & Travel",
    "pet collective": "Nature & Travel", "paws & claws": "Nature & Travel", "naturescape": "Nature & Travel",
    "get.factual": "Documentary", "cosmic frontiers": "History & Science", "startalk tv": "History & Science",
    "this old house classic": "Food & Home", "this old house shorts": "Food & Home",
    "mecum tv": "Lifestyle", "fashiontv": "Lifestyle", "the doctors": "Lifestyle",
    "5-minute crafts": "Lifestyle", "123go!": "Lifestyle", "creator television": "Lifestyle",
    "bbc game shows": "Game Shows", "estella games": "Game Shows", "estrella games": "Game Shows",
    "bonanza-billies tv": "Westerns",
}

NAME_RULES = [
    ("Local News", r"\b(?:local now|very (?:carolina|boston|omaha|milwaukee|new mexico|s\. carolina)|fox local)\b|\b(?:w[a-z]{2,3}|k[a-z]{2,3})\s+(?:channel|news)\b"),
    ("News", r"\b(?:news|newsmax|bloomberg|reuters|euronews|weather|accuweather|court tv|france 24|telemundo al dia|entravision ahora)\b"),
    ("Sports", r"\b(?:sports?|deportes|nfl|nba|mlb|nhl|f1|formula 1|football|soccer|golf|tennis|poker|racing|mma|ufc|wrestling|boxing|kickboxing|pickleball|billiards|darts|cornhole|bowling|cricket|surf|fight|strongman|wwe|speedvision)\b"),
    ("Kids", r"\b(?:kids?|kidz|junior|cartoon|animated|nickelodeon|nick jr|baby shark|teletubbies|barney|lego|sonic|pokemon|paw patrol|wiggles|beyblade|garfield|hasbro|wonderland)\b"),
    ("Anime", r"\b(?:anime|crunchyroll|hidive)\b"),
    ("Game Shows", r"\b(?:game shows?|gameshow|quiz|family feud|deal or no deal|price is right|wheel of fortune|jeopardy)\b"),
    ("Crime", r"\b(?:crime|crimen|detectives?|cops|forensic|investigation|mysteries|mystery|cold case|court|law & crime|law and crime|true crime|sheriffs?|patrol|behind bars|delito|suspect)\b"),
    ("Sci-Fi & Horror", r"\b(?:sci[- ]?fi|horror|paranormal|ghost|shudder|alien|thriller|dystopia|scream|fright|dread|monsters?|stargate|outer limits|dark matter|spoopy|halloween)\b"),
    ("Westerns", r"\b(?:western|westerns|cowboy|gunsmoke|películas del oeste|peliculas del oeste)\b"),
    ("Classics", r"\b(?:classic tv|classics|clásico|clasico|retro|oldies|vintage tv|flashback 70s|80's sitcom|remember the .80s)\b"),
    ("Food & Home", r"\b(?:food|kfood|cooking|cook|kitchen|chef|tastemade|home|diy|garden|renovation|baking|emeril|property brothers|repair shop|crafts|yummy|dine)\b"),
    ("Nature & Travel", r"\b(?:nature|naturaleza|wildlife|travel|traveler|outdoors|earth|animal|adventure|wild|paws|pack leader|wicked tuna|alive|survive or die)\b"),
    ("History & Science", r"\b(?:history|science|space|nasa|curiosity|smithsonian|cosmic|startalk|factual)\b"),
    ("Documentary", r"\b(?:documentary|documentaries|docurama|docs|factual)\b"),
    ("Music", r"\b(?:music|vevo|mtv|stingray|concert|karaoke|billboard|xite|k-pop|hip-hop|r&b|jazz|rock|hits|y2k|trace urban|qwest)\b"),
    ("Comedy", r"\b(?:comedy|funny|laugh|lol|sitcom|mr\. bean|corner gas)\b"),
    ("Reality", r"\b(?:reality|housewives|bachelor|survivor|big brother|cheaters|dance moms|duck dynasty|osbournes|lockup|bride|gladiators|biggest loser|fear factor|growing up hip hop)\b"),
    ("Lifestyle", r"\b(?:lifestyle|fashion|weddings|wellness|fitness|perform by lifetime|pop culture|creator|crafts|prof g|medical|doctors?)\b"),
    ("Movies", r"\b(?:movie|movies|cinema|cinevault|cinelife|filmrise|films?|miramax|mgm presents|tribeca|blackpix|pelimex|movieitaly|ifc films)\b"),
    ("TV", r"\b(?:drama|k-drama|soap|primetime|free ?tv|tv live|thrillers|hunter|librarians|weeds|nurse jackie|heat of the night)\b"),
]

GENERIC = {"united states", "other", "global", "international", "featured", ""}


def normalize_group(group: str, name: str) -> str:
    g = (group or "").strip().casefold()
    if g in ALIASES:
        return ALIASES[g]
    for raw, normalized in ALIASES.items():
        if raw and raw in g and g not in GENERIC:
            return normalized
    n = (name or "").strip().casefold()
    if n in EXACT:
        return EXACT[n]
    for category, pattern in NAME_RULES:
        if re.search(pattern, n, re.IGNORECASE):
            return category
    return "Other"


def replace_group(extinf: str, category: str) -> str:
    if re.search(r'group-title="[^"]*"', extinf, flags=re.IGNORECASE):
        return re.sub(r'group-title="[^"]*"', f'group-title="{category}"', extinf, count=1, flags=re.IGNORECASE)
    comma = extinf.rfind(",")
    if comma == -1:
        return extinf
    return extinf[:comma] + f' group-title="{category}"' + extinf[comma:]


def parse_name(extinf: str) -> str:
    return extinf.rsplit(",", 1)[1].strip() if "," in extinf else ""


def main():
    database = json.loads(SOURCES.read_text(encoding="utf-8"))
    category_by_name = {}
    counts = Counter()
    recovered = 0
    other_audit = []

    for item in database:
        name = item.get("name", "")
        original = item.get("group", "Other")
        item["original_group"] = original

        useful_group = original
        recovered_from = ""
        if original.strip().casefold() in GENERIC:
            for fallback in item.get("fallbacks", []):
                fg = (fallback.get("group") or "").strip()
                if fg.casefold() not in GENERIC:
                    useful_group = fg
                    recovered_from = fallback.get("source", "fallback")
                    recovered += 1
                    break

        category = normalize_group(useful_group, name)
        item["display_category"] = category
        category_by_name[name] = category
        counts[category] += 1

        if category == "Other":
            other_audit.append({
                "name": name,
                "source": item.get("primary", {}).get("source", "Unknown"),
                "original_group": original,
                "useful_group": useful_group,
                "recovered_from": recovered_from,
            })

    lines = MASTER.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        if line.startswith("#EXTINF"):
            name = parse_name(line)
            category = category_by_name.get(name, "Other")
            line = replace_group(line, category)
        out.append(line)
    MASTER.write_text("\n".join(out) + "\n", encoding="utf-8")

    SOURCES.write_text(json.dumps(database, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    report = REPORT.read_text(encoding="utf-8")
    marker = "\n================================================================\nV4 NORMALIZED CATEGORY SUMMARY\n"
    if marker in report:
        report = report.split(marker, 1)[0].rstrip() + "\n"
    report += marker
    report += "================================================================\n\n"
    report += "Display taxonomy: 21 CarPlay categories\n"
    report += f"Channels categorized: {sum(counts.values())}\n"
    report += f"Generic categories recovered from fallback metadata: {recovered}\n"
    report += "United States display category: 0\n\n"
    for category in CATEGORIES:
        report += f"  {category}: {counts.get(category, 0)}\n"

    report += "\n================================================================\n"
    report += "V4 OTHER CHANNEL AUDIT\n"
    report += "================================================================\n\n"
    report += f"Unresolved Other channels: {len(other_audit)}\n"
    report += "Remaining entries are intentionally left unresolved rather than forcing a low-confidence category.\n\n"
    for entry in other_audit:
        report += (
            f"  {entry['name']} | source={entry['source']} | "
            f"original={entry['original_group']} | useful={entry['useful_group']}\n"
        )

    REPORT.write_text(report, encoding="utf-8")

    print("V4 category normalization complete")
    print(f"Channels categorized: {sum(counts.values())}")
    print(f"Fallback metadata recoveries: {recovered}")
    print(f"Unresolved Other channels: {len(other_audit)}")
    print("United States display category: 0")
    for category in CATEGORIES:
        print(f"  {category}: {counts.get(category, 0)}")


if __name__ == "__main__":
    main()
