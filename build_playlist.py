#!/usr/bin/env python3

"""
CarPlay TV Master Playlist Builder
----------------------------------
Combines U.S. FAST television playlists into one deduplicated M3U.

Source priority:
1. Samsung TV Plus US
2. Pluto TV US
3. Roku
4. Tubi
5. Plex US

The first occurrence of a normalized channel name wins.

Generated files:
- master.m3u
- playlist_report.txt
"""

from __future__ import annotations

import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path


OUTPUT_FILE = Path("master.m3u")
REPORT_FILE = Path("playlist_report.txt")


SOURCES = [
    {
        "name": "Samsung TV Plus",
        "short": "Samsung",
        "url": (
            "https://raw.githubusercontent.com/"
            "BuddyChewChew/app-m3u-generator/main/"
            "playlists/samsungtvplus_us.m3u"
        ),
    },
    {
        "name": "Pluto TV",
        "short": "Pluto",
        "url": (
            "https://raw.githubusercontent.com/"
            "BuddyChewChew/app-m3u-generator/main/"
            "playlists/plutotv_us.m3u"
        ),
    },
    {
        "name": "Roku",
        "short": "Roku",
        "url": (
            "https://raw.githubusercontent.com/"
            "BuddyChewChew/app-m3u-generator/main/"
            "playlists/roku_all.m3u"
        ),
    },
    {
        "name": "Tubi",
        "short": "Tubi",
        "url": (
            "https://raw.githubusercontent.com/"
            "BuddyChewChew/app-m3u-generator/main/"
            "playlists/tubi_all.m3u"
        ),
    },
    {
        "name": "Plex",
        "short": "Plex",
        "url": (
            "https://raw.githubusercontent.com/"
            "BuddyChewChew/app-m3u-generator/main/"
            "playlists/plex_us.m3u"
        ),
    },
]


def download_text(url: str) -> str:
    """Download an upstream M3U playlist."""

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 CarPlay-TV-Playlist-Builder/1.0"
            )
        },
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()

    return data.decode("utf-8", errors="replace")


def parse_attribute(extinf: str, attribute: str) -> str:
    pattern = rf'{re.escape(attribute)}="([^"]*)"'
    match = re.search(pattern, extinf, flags=re.IGNORECASE)

    if match:
        return match.group(1).strip()

    return ""


def parse_playlist(text: str) -> list[dict]:
    """
    Convert an M3U playlist into channel dictionaries.

    Each channel retains the original EXTINF metadata so logos,
    IDs and other useful fields are preserved.
    """

    lines = text.splitlines()
    channels = []

    index = 0

    while index < len(lines):
        line = lines[index].strip()

        if not line.startswith("#EXTINF"):
            index += 1
            continue

        extinf = line

        if "," in extinf:
            name = extinf.rsplit(",", 1)[1].strip()
        else:
            name = ""

        stream_url = ""
        extra_lines = []

        search_index = index + 1

        while search_index < len(lines):
            candidate = lines[search_index].strip()

            if not candidate:
                search_index += 1
                continue

            if candidate.startswith("#EXTINF"):
                break

            if candidate.startswith("#"):
                extra_lines.append(candidate)
                search_index += 1
                continue

            stream_url = candidate
            break

        if name and stream_url:
            channels.append(
                {
                    "name": name,
                    "group": parse_attribute(
                        extinf,
                        "group-title",
                    )
                    or "Other",
                    "logo": parse_attribute(
                        extinf,
                        "tvg-logo",
                    ),
                    "tvg_id": parse_attribute(
                        extinf,
                        "tvg-id",
                    ),
                    "extinf": extinf,
                    "extra_lines": extra_lines,
                    "url": stream_url,
                }
            )

        index = max(search_index + 1, index + 1)

    return channels


def normalize_name(name: str) -> str:
    """
    Normalize channel names for conservative duplicate detection.

    Examples:
        ABC News Live -> abcnewslive
        ABC NEWS LIVE -> abcnewslive
        Bob Ross Channel -> bobrosschannel
    """

    value = name.casefold()

    value = value.replace("&", "and")

    value = re.sub(
        r"\b(?:hd|fhd|uhd|4k|fast)\b",
        "",
        value,
    )

    value = re.sub(
        r"[^a-z0-9]+",
        "",
        value,
    )

    return value


def add_source_tag(extinf: str, source: str) -> str:
    """
    Add our own source metadata without destroying the provider's
    original metadata.
    """

    if 'source="' in extinf.lower():
        return extinf

    comma_position = extinf.rfind(",")

    if comma_position == -1:
        return extinf

    before_name = extinf[:comma_position]
    channel_name = extinf[comma_position:]

    return (
        f'{before_name} source="{source}"'
        f"{channel_name}"
    )


def build_master():
    seen_names = {}
    master_channels = []

    report = []

    report.append(
        "CARPLAY TV MASTER PLAYLIST REPORT"
    )
    report.append(
        "=" * 50
    )
    report.append("")

    total_downloaded = 0

    for source in SOURCES:
        source_name = source["name"]
        source_short = source["short"]
        source_url = source["url"]

        print(
            f"Downloading {source_name}..."
        )

        try:
            text = download_text(source_url)
        except Exception as exc:
            message = (
                f"ERROR downloading {source_name}: {exc}"
            )

            print(message)
            report.append(message)
            report.append("")

            continue

        channels = parse_playlist(text)

        downloaded_count = len(channels)
        total_downloaded += downloaded_count

        added = 0
        duplicates = 0

        duplicate_examples = []

        for channel in channels:
            normalized = normalize_name(
                channel["name"]
            )

            if not normalized:
                continue

            if normalized in seen_names:
                duplicates += 1

                if len(duplicate_examples) < 20:
                    original = seen_names[normalized]

                    duplicate_examples.append(
                        (
                            channel["name"],
                            original["name"],
                            original["source"],
                        )
                    )

                continue

            channel["source"] = source_short

            seen_names[normalized] = channel
            master_channels.append(channel)

            added += 1

        report.append(source_name)
        report.append("-" * len(source_name))

        report.append(
            f"Channels in source: {downloaded_count}"
        )

        report.append(
            f"New unique channels added: {added}"
        )

        report.append(
            f"Duplicates skipped: {duplicates}"
        )

        if duplicate_examples:
            report.append("")
            report.append(
                "Sample duplicates:"
            )

            for (
                duplicate_name,
                kept_name,
                kept_source,
            ) in duplicate_examples:

                report.append(
                    "  "
                    f"{duplicate_name} "
                    "-> already kept as "
                    f"{kept_name} "
                    f"from {kept_source}"
                )

        report.append("")

        print(
            f"  {downloaded_count} channels"
        )

        print(
            f"  {added} new unique channels"
        )

        print(
            f"  {duplicates} duplicates skipped"
        )


    #
    # Write master M3U
    #

    output_lines = [
        "#EXTM3U",
    ]

    for channel in master_channels:

        output_lines.append(
            add_source_tag(
                channel["extinf"],
                channel["source"],
            )
        )

        output_lines.extend(
            channel["extra_lines"]
        )

        output_lines.append(
            channel["url"]
        )


    OUTPUT_FILE.write_text(
        "\n".join(output_lines) + "\n",
        encoding="utf-8",
    )


    #
    # Statistics
    #

    source_counts = Counter(
        channel["source"]
        for channel in master_channels
    )

    group_counts = Counter(
        channel["group"]
        for channel in master_channels
    )


    report.append(
        "=" * 50
    )

    report.append(
        "MASTER PLAYLIST SUMMARY"
    )

    report.append(
        "=" * 50
    )

    report.append("")

    report.append(
        f"Total upstream channel entries: "
        f"{total_downloaded}"
    )

    report.append(
        f"Final unique channels: "
        f"{len(master_channels)}"
    )

    report.append(
        f"Duplicates removed: "
        f"{total_downloaded - len(master_channels)}"
    )

    report.append("")

    report.append(
        "Final channels by source:"
    )

    for source, count in source_counts.items():
        report.append(
            f"  {source}: {count}"
        )

    report.append("")

    report.append(
        "Top categories:"
    )

    for group, count in group_counts.most_common(30):
        report.append(
            f"  {group}: {count}"
        )


    REPORT_FILE.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )


    print("")
    print(
        "=" * 50
    )

    print(
        f"MASTER PLAYLIST COMPLETE"
    )

    print(
        f"Unique channels: "
        f"{len(master_channels)}"
    )

    print(
        f"Created: {OUTPUT_FILE}"
    )

    print(
        f"Created: {REPORT_FILE}"
    )

    print(
        "=" * 50
    )


if __name__ == "__main__":
    try:
        build_master()

    except KeyboardInterrupt:
        print(
            "\nCancelled."
        )
        sys.exit(1)

    except Exception as exc:
        print(
            f"\nBuild failed: {exc}"
        )
        raise
