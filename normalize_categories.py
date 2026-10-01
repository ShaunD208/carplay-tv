#!/usr/bin/env python3
"""CarPlay TV v4 category normalizer.

Runs after build_playlist.py. It preserves v3 provider priority, language filtering,
fallbacks and validation, while replacing inconsistent upstream group-title values
with one 21-category CarPlay taxonomy. Original categories remain in
channel_sources.json as original_group.
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
    "news": "News", "news & opinion": "News", "news + opinion": "News",
    "sports": "Sports", "sports & outdoors": "Sports", "sports on now": "Sports",
    "motor sports": "Sports", "motorsports": "Sports",
    "movies": "Movies", "movie": "Movies",
    "tv & entertainment": "TV", "action & drama": "TV", "drama": "TV",
    "hit tv": "TV", "daytime tv": "TV", "daytime": "TV",
    "comedy": "Comedy",
    "crime": "Crime", "true crime": "Crime",
    "reality": "Reality", "reality tv": "Reality", "reality competition": "Reality",
    "competition reality": "Reality", "big brother live": "Reality",
    "classic tv": "Classics", "classics": "Classics",
    "western & classic tv": "Classics",
    "sci-fi": "Sci-Fi & Horror", "sci-fi & horror": "Sci-Fi & Horror",
    "horror": "Sci-Fi & Horror", "chills & thrills": "Sci-Fi & Horror",
    "kids": "Kids", "kids & family": "Kids",
    "music": "Music", "music videos": "Music",
    "home & food": "Food & Home", "home + food": "Food & Home",
    "food & home": "Food & Home", "cooking": "Food & Home",
    "lifestyle": "Lifestyle", "lifestyle & pop culture": "Lifestyle",
    "nature, history & science": "History & Science",
    "history + science": "History & Science", "history & science": "History & Science",
    "nature & travel": "Nature & Travel", "travel": "Nature & Travel",
    "documentary": "Documentary", "documentaries": "Documentary",
    "anime": "Anime", "anime & gaming": "Anime", "anime+": "Anime",
    "game shows": "Game Shows", "daytime + game shows": "Game Shows",
    "westerns": "Westerns", "western": "Westerns",
}

NAME_RULES = [
    ("Local News", r"\b(?:local|news)\b.*\b(?:[kw][a-z]{2,4}|fox|abc|cbs|nbc)\b|\b(?:fox|abc|cbs|nbc)\s+(?:local|news)\b|\bvery\s+(?:boston|omaha|milwaukee|new mexico|s\. carolina)\b"),
    ("News", r"\b(?:news|newsmax|bloomberg|reuters|euronews|weather|accuweather|court tv)\b"),
    ("Sports", r"\b(?:sports|nfl|nba|mlb|nhl|f1|formula 1|football|soccer|golf|tennis|poker|racing|mma|ufc|wrestling|boxing|pickleball|billiards|darts)\b"),
    ("Kids", r"\b(?:kids|junior|cartoon|nickelodeon|nick jr|baby shark|teletubbies|barney|lego|sonic|pokemon|paw patrol)\b"),
    ("Anime", r"\b(?:anime|crunchyroll|hidive)\b"),
    ("Game Shows", r"\b(?:game show|gameshow|quiz|family feud|deal or no deal|price is right|wheel of fortune|jeopardy)\b"),
    ("Crime", r"\b(?:crime|cops|forensic|investigation|mysteries|mystery|cold case|court|law & crime|law and crime|true crime)\b"),
    ("Sci-Fi & Horror", r"\b(?:sci[- ]?fi|horror|paranormal|ghost|shudder|alien|thriller|dystopia)\b"),
    ("Westerns", r"\b(?:western|westerns|cowboy|gunsmoke)\b"),
    ("Classics", r"\b(?:classic tv|classics|retro tv|oldies|vintage tv)\b"),
    ("Food & Home", r"\b(?:food|cooking|cook|kitchen|chef|tastemade|home|diy|garden|renovation)\b"),
    ("Nature & Travel", r"\b(?:nature|wildlife|travel|outdoors|earth|animal|adventure)\b"),
    ("History & Science", r"\b(?:history|science|space|nasa|curiosity|smithsonian)\b"),
    ("Documentary", r"\b(?:documentary|documentaries|docurama|docs)\b"),
    ("Music", r"\b(?:music|vevo|mtv|stingray|concert|karaoke|billboard)\b"),
    ("Comedy", r"\b(?:comedy|funny|laugh|lol)\b"),
    ("Reality", r"\b(?:reality|housewives|bachelor|survivor|big brother|cheaters)\b"),
    ("Lifestyle", r"\b(?:lifestyle|fashion|weddings|wellness|fitness|perform by lifetime)\b"),
    ("Movies", r"\b(?:movie|movies|cinema|cinevault|filmrise|film|miramax)\b"),
]

GENERIC = {"united states", "other", "global", "international", "featured", ""}


def normalize_group(group: str, name: str) -> str:
    g = (group or "").strip().casefold()
    if g in ALIASES:
        return ALIASES[g]
    for raw, normalized in ALIASES.items():
        if raw and raw in g and g not in GENERIC:
            return normalized
    n = (name or "").casefold()
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
    report += "These are intentionally listed so category rules can be improved from real channels rather than guesses.\n\n"
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
