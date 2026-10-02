#!/usr/bin/env python3
"""Add individually approved custom channels after the automated provider build.

This stage runs after language/category cleanup so custom channels survive every daily
rebuild without importing an entire additional FAST provider.
"""

import json
from pathlib import Path

MASTER = Path("master.m3u")
SOURCES = Path("channel_sources.json")
REPORT = Path("playlist_report.txt")

CUSTOM_CHANNELS = [
    {
        "name": "Schwab Network",
        "normalized_name": "schwabnetwork",
        "group": "News",
        "display_category": "News",
        "logo": "",
        "tvg_id": "SchwabNetwork.us@SD",
        "source": "Schwab / VIZIO",
        "url": "https://tdameritrade-vizio.amagi.tv/playlistR1080p.m3u8",
    }
]


def main():
    playlist = MASTER.read_text(encoding="utf-8")
    database = json.loads(SOURCES.read_text(encoding="utf-8"))
    existing_names = {item.get("name", "").casefold() for item in database}
    added = []

    for channel in CUSTOM_CHANNELS:
        if channel["name"].casefold() in existing_names:
            continue

        extinf = (
            f'#EXTINF:-1 tvg-id="{channel["tvg_id"]}" '
            f'tvg-logo="{channel["logo"]}" '
            f'group-title="{channel["group"]}" '
            f'source="{channel["source"]}" fallbacks="0",{channel["name"]}'
        )
        if not playlist.endswith("\n"):
            playlist += "\n"
        playlist += extinf + "\n" + channel["url"] + "\n"

        database.append({
            "name": channel["name"],
            "normalized_name": channel["normalized_name"],
            "group": channel["group"],
            "logo": channel["logo"],
            "tvg_id": channel["tvg_id"],
            "primary": {"source": channel["source"], "url": channel["url"]},
            "fallbacks": [],
            "original_group": channel["group"],
            "display_category": channel["display_category"],
            "custom": True,
        })
        existing_names.add(channel["name"].casefold())
        added.append(channel["name"])

    MASTER.write_text(playlist, encoding="utf-8")
    SOURCES.write_text(json.dumps(database, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if added:
        with REPORT.open("a", encoding="utf-8") as report:
            report.write("\n================================================================\n")
            report.write("CUSTOM CHANNELS\n")
            report.write("================================================================\n\n")
            for name in added:
                report.write(f"  ADDED: {name}\n")
            report.write(f"\nCustom channels added: {len(added)}\n")

    print(f"Custom channels added: {len(added)}")
    for name in added:
        print(f"  {name}")


if __name__ == "__main__":
    main()
