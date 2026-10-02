#!/usr/bin/env python3
"""Final conservative English-only cleanup for CarPlay TV.

Runs after category normalization. This catches clearly non-English feeds that arrive
under generic upstream groups (especially Roku/Plex), while deliberately leaving
ambiguous/international English channels alone.
"""

import json
import re
from collections import Counter
from pathlib import Path

MASTER = Path("master.m3u")
SOURCES = Path("channel_sources.json")
REPORT = Path("playlist_report.txt")

# Strong indicators only. These are intended to avoid false positives.
PATTERNS = [
    r"\ben espa(?:ñ|n)ol\b", r"\bespa(?:ñ|n)ol\b", r"\bnoticias\b",
    r"\bnovelas?\b", r"\btelenovelas?\b", r"\bcine rom[aá]ntico\b",
    r"\bcine latino\b", r"\bpel[ií]culas?\b", r"\blucha plus\b",
    r"\bgata salvaje\b", r"\bnovel[ií]sima\b", r"\btelemundo\b",
    r"\bestrella(?:tv| news)?\b", r"\bazteca\b", r"\bcanela\.tv\b",
    r"\bvix\b", r"\btelevisa\b", r"\bunivision\b", r"\bcaracol\b",
    r"\brcn\b", r"\bfran[cç]ais\b", r"\bportugu[eê]s\b",
    r"\bdeutsch\b", r"\bitaliano\b", r"\bhindi\b", r"\bpunjabi\b",
    r"\burdu\b", r"\barabic\b", r"\bkorean\b", r"\bjapanese\b",
    r"\bchinese\b", r"\btagalog\b", r"\bvietnamese\b", r"\bthai\b",
]
RX = re.compile("|".join(f"(?:{p})" for p in PATTERNS), re.IGNORECASE)

# Known English-language brands/titles that may contain terms which otherwise look
# foreign. Keep list small and explicit.
KEEP = set()


def non_english(name: str, original_group: str = "") -> bool:
    n = (name or "").strip()
    if n.casefold() in KEEP:
        return False
    text = f"{n} {original_group or ''}"
    return bool(RX.search(text))


def parse_name(extinf: str) -> str:
    return extinf.rsplit(",", 1)[1].strip() if "," in extinf else ""


def filter_m3u(path: Path, removed_names: set[str]):
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("#EXTINF"):
            out.append(line)
            i += 1
            continue
        name = parse_name(line)
        block = [line]
        i += 1
        while i < len(lines) and not lines[i].startswith("#EXTINF"):
            block.append(lines[i])
            i += 1
        if name not in removed_names:
            out.extend(block)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    db = json.loads(SOURCES.read_text(encoding="utf-8"))
    kept = []
    removed = []
    by_source = Counter()

    for item in db:
        name = item.get("name", "")
        original = item.get("original_group", item.get("group", ""))
        if non_english(name, original):
            removed.append(item)
            by_source[item.get("primary", {}).get("source", "Unknown")] += 1
        else:
            kept.append(item)

    removed_names = {item.get("name", "") for item in removed}
    SOURCES.write_text(json.dumps(kept, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    filter_m3u(MASTER, removed_names)

    report = REPORT.read_text(encoding="utf-8")
    marker = "\n================================================================\nFINAL ENGLISH-ONLY CLEANUP\n"
    if marker in report:
        report = report.split(marker, 1)[0].rstrip() + "\n"
    report += marker
    report += "================================================================\n\n"
    report += f"Channels before final cleanup: {len(db)}\n"
    report += f"Clearly non-English channels removed: {len(removed)}\n"
    report += f"Final English-focused channels: {len(kept)}\n\n"
    report += "Removed by primary source:\n"
    for source, count in sorted(by_source.items()):
        report += f"  {source}: {count}\n"
    report += "\nRemoved channels:\n"
    for item in removed:
        report += f"  {item.get('name','')} | source={item.get('primary',{}).get('source','Unknown')} | original={item.get('original_group', item.get('group',''))}\n"
    REPORT.write_text(report, encoding="utf-8")

    print(f"Final language cleanup removed {len(removed)} channels; {len(kept)} remain.")


if __name__ == "__main__":
    main()
