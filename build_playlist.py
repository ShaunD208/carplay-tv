#!/usr/bin/env python3

"""
CarPlay TV Master Playlist Builder v2
=====================================

Goals:
- Combine major U.S. FAST providers.
- Prefer providers in a defined priority order.
- Conservatively deduplicate channel names.
- Preserve alternate/fallback feeds.
- Perform server-side HLS/URL validation.
- Never confuse server validation with browser/CORS validation.
- Generate reports for actual browser testing.

Source priority:
1. Samsung TV Plus US
2. Pluto TV US
3. Roku
4. Tubi
5. Plex US

Generated files:
- master.m3u
- playlist_report.txt
- browser_test_candidates.m3u
- channel_sources.json
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path


OUTPUT_FILE = Path("master.m3u")
REPORT_FILE = Path("playlist_report.txt")
TEST_FILE = Path("browser_test_candidates.m3u")
SOURCES_FILE = Path("channel_sources.json")


USER_AGENT = "Mozilla/5.0 CarPlay-TV-Playlist-Builder/2.0"

VALIDATION_TIMEOUT = 12

# Validate only a representative sample during every automated build.
# Validating 1,500+ streams every day would be unnecessarily heavy.
VALIDATION_SAMPLE_PER_SOURCE = 12


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


def request_url(
    url: str,
    timeout: int = 60,
    max_bytes: int | None = None,
):
    """
    Download a URL with a browser-like user agent.

    max_bytes allows validation to read only the beginning of
    a response rather than downloading unnecessary data.
    """

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
    )

    response = urllib.request.urlopen(
        request,
        timeout=timeout,
    )

    if max_bytes is None:
        data = response.read()
    else:
        data = response.read(max_bytes)

    final_url = response.geturl()
    content_type = response.headers.get(
        "Content-Type",
        "",
    )

    response.close()

    return data, final_url, content_type


def download_text(url: str) -> str:
    data, _, _ = request_url(url)

    return data.decode(
        "utf-8",
        errors="replace",
    )


def parse_attribute(
    extinf: str,
    attribute: str,
) -> str:

    pattern = rf'{re.escape(attribute)}="([^"]*)"'

    match = re.search(
        pattern,
        extinf,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1).strip()

    return ""


def parse_playlist(text: str) -> list[dict]:
    """
    Parse EXTINF entries while preserving useful metadata.
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

        extra_lines = []
        stream_url = ""

        search_index = index + 1

        while search_index < len(lines):

            candidate = lines[
                search_index
            ].strip()

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
                    "group": (
                        parse_attribute(
                            extinf,
                            "group-title",
                        )
                        or "Other"
                    ),
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

        index = max(
            search_index + 1,
            index + 1,
        )

    return channels


def normalize_name(name: str) -> str:
    """
    Conservative duplicate matching.

    We intentionally do NOT try to merge semantic aliases such as:
        ACCDN
        ACC Digital Network

    False duplicates are worse than a small number of duplicates.
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


def add_metadata(
    extinf: str,
    source: str,
    fallback_count: int,
) -> str:
    """
    Add our own metadata while preserving upstream EXTINF fields.
    """

    comma_position = extinf.rfind(",")

    if comma_position == -1:
        return extinf

    before_name = extinf[:comma_position]
    channel_name = extinf[comma_position:]

    return (
        f'{before_name} '
        f'source="{source}" '
        f'fallbacks="{fallback_count}"'
        f"{channel_name}"
    )


def validate_stream(url: str) -> dict:
    """
    Server-side stream validation.

    IMPORTANT:
    A PASS here does NOT prove browser compatibility.

    Browsers enforce CORS and other client-side restrictions that
    Python does not. Final compatibility must be tested in our
    GitHub Pages player / APTV browser.
    """

    result = {
        "status": "unknown",
        "http_reachable": False,
        "looks_like_hls": False,
        "final_url": url,
        "content_type": "",
        "reason": "",
    }

    try:

        data, final_url, content_type = request_url(
            url,
            timeout=VALIDATION_TIMEOUT,
            max_bytes=128_000,
        )

        result["http_reachable"] = True
        result["final_url"] = final_url
        result["content_type"] = content_type

        text = data.decode(
            "utf-8",
            errors="replace",
        )

        looks_like_hls = (
            "#EXTM3U" in text
            or "mpegurl" in content_type.lower()
            or ".m3u8" in final_url.lower()
        )

        result["looks_like_hls"] = looks_like_hls

        if looks_like_hls:
            result["status"] = "server-pass"
            result["reason"] = (
                "Manifest reachable and appears to be HLS"
            )
        else:
            result["status"] = "server-warning"
            result["reason"] = (
                "URL reachable but response was not clearly HLS"
            )

    except urllib.error.HTTPError as exc:

        result["status"] = "server-fail"

        result["reason"] = (
            f"HTTP {exc.code}"
        )

    except urllib.error.URLError as exc:

        result["status"] = "server-fail"

        result["reason"] = (
            f"URL error: {exc.reason}"
        )

    except Exception as exc:

        result["status"] = "server-fail"

        result["reason"] = str(exc)

    return result


def choose_validation_samples(
    channels: list[dict],
) -> list[dict]:
    """
    Pick representative channels from each provider.

    We spread samples through each provider's contribution rather
    than simply checking the first N channels.
    """

    by_source = defaultdict(list)

    for channel in channels:
        by_source[channel["source"]].append(
            channel
        )

    selected = []

    for source in [
        item["short"]
        for item in SOURCES
    ]:

        candidates = by_source.get(
            source,
            [],
        )

        if not candidates:
            continue

        sample_size = min(
            VALIDATION_SAMPLE_PER_SOURCE,
            len(candidates),
        )

        if sample_size == 1:
            selected.append(candidates[0])
            continue

        indexes = {
            round(
                i
                * (len(candidates) - 1)
                / (sample_size - 1)
            )
            for i in range(sample_size)
        }

        for index in sorted(indexes):
            selected.append(
                candidates[index]
            )

    return selected


def build_master():

    primary_by_key = {}

    ordered_keys = []

    source_stats = {}

    total_downloaded = 0


    report = [
        "CARPLAY TV MASTER PLAYLIST REPORT V2",
        "=" * 60,
        "",
    ]


    #
    # Download and merge providers
    #

    for source in SOURCES:

        source_name = source["name"]
        source_short = source["short"]

        print(
            f"Downloading {source_name}..."
        )

        try:
            text = download_text(
                source["url"]
            )

        except Exception as exc:

            message = (
                f"ERROR downloading "
                f"{source_name}: {exc}"
            )

            print(message)

            report.extend(
                [
                    message,
                    "",
                ]
            )

            continue


        channels = parse_playlist(text)

        total_downloaded += len(channels)

        added = 0
        duplicate_count = 0

        duplicate_examples = []


        for channel in channels:

            key = normalize_name(
                channel["name"]
            )

            if not key:
                continue

            feed = {
                "source": source_short,
                "name": channel["name"],
                "url": channel["url"],
                "logo": channel["logo"],
                "group": channel["group"],
                "tvg_id": channel["tvg_id"],
            }


            if key not in primary_by_key:

                channel["source"] = source_short
                channel["fallbacks"] = []

                primary_by_key[key] = channel

                ordered_keys.append(key)

                added += 1

            else:

                duplicate_count += 1

                primary = primary_by_key[key]

                #
                # Don't store an identical URL as a fallback.
                #

                existing_urls = {
                    primary["url"]
                }

                existing_urls.update(
                    fallback["url"]
                    for fallback
                    in primary["fallbacks"]
                )

                if feed["url"] not in existing_urls:

                    primary["fallbacks"].append(
                        feed
                    )

                if len(
                    duplicate_examples
                ) < 20:

                    duplicate_examples.append(
                        (
                            channel["name"],
                            primary["name"],
                            primary["source"],
                        )
                    )


        source_stats[source_short] = {
            "downloaded": len(channels),
            "added": added,
            "duplicates": duplicate_count,
        }


        report.extend(
            [
                source_name,
                "-" * len(source_name),
                (
                    "Channels in source: "
                    f"{len(channels)}"
                ),
                (
                    "New unique channels added: "
                    f"{added}"
                ),
                (
                    "Duplicates / alternate feeds: "
                    f"{duplicate_count}"
                ),
            ]
        )


        if duplicate_examples:

            report.extend(
                [
                    "",
                    "Sample alternate feeds:",
                ]
            )

            for (
                duplicate_name,
                kept_name,
                kept_source,
            ) in duplicate_examples:

                report.append(
                    "  "
                    f"{duplicate_name}"
                    " -> primary "
                    f"{kept_name}"
                    f" from {kept_source}"
                )


        report.append("")


        print(
            f"  {len(channels)} entries"
        )

        print(
            f"  {added} unique channels added"
        )

        print(
            f"  {duplicate_count} alternate feeds"
        )


    master_channels = [
        primary_by_key[key]
        for key in ordered_keys
    ]


    #
    # Server-side validation sample
    #

    print("")
    print(
        "Running representative "
        "server-side stream validation..."
    )


    validation_samples = (
        choose_validation_samples(
            master_channels
        )
    )


    validation_results = []

    for number, channel in enumerate(
        validation_samples,
        start=1,
    ):

        print(
            f"  [{number}/"
            f"{len(validation_samples)}] "
            f"{channel['source']} - "
            f"{channel['name']}"
        )

        result = validate_stream(
            channel["url"]
        )

        validation_results.append(
            {
                "source": channel["source"],
                "name": channel["name"],
                "url": channel["url"],
                **result,
            }
        )


    #
    # Write master M3U
    #

    output_lines = [
        "#EXTM3U",
    ]


    for channel in master_channels:

        output_lines.append(
            add_metadata(
                channel["extinf"],
                channel["source"],
                len(
                    channel["fallbacks"]
                ),
            )
        )

        output_lines.extend(
            channel["extra_lines"]
        )

        output_lines.append(
            channel["url"]
        )


    OUTPUT_FILE.write_text(
        "\n".join(
            output_lines
        )
        + "\n",
        encoding="utf-8",
    )


    #
    # Write browser test candidate playlist
    #

    test_lines = [
        "#EXTM3U",
    ]

    for item in validation_results:

        channel = next(
            (
                channel
                for channel
                in master_channels
                if channel["source"]
                == item["source"]
                and channel["name"]
                == item["name"]
            ),
            None,
        )

        if channel is None:
            continue

        test_lines.append(
            add_metadata(
                channel["extinf"],
                channel["source"],
                len(
                    channel["fallbacks"]
                ),
            )
        )

        test_lines.extend(
            channel["extra_lines"]
        )

        test_lines.append(
            channel["url"]
        )


    TEST_FILE.write_text(
        "\n".join(
            test_lines
        )
        + "\n",
        encoding="utf-8",
    )


    #
    # Write source/fallback database
    #

    source_database = []

    for channel in master_channels:

        source_database.append(
            {
                "name": channel["name"],
                "normalized_name": (
                    normalize_name(
                        channel["name"]
                    )
                ),
                "group": channel["group"],
                "logo": channel["logo"],
                "tvg_id": channel["tvg_id"],
                "primary": {
                    "source": (
                        channel["source"]
                    ),
                    "url": channel["url"],
                },
                "fallbacks": (
                    channel["fallbacks"]
                ),
            }
        )


    SOURCES_FILE.write_text(
        json.dumps(
            source_database,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


    #
    # Reporting
    #

    source_counts = Counter(
        channel["source"]
        for channel
        in master_channels
    )

    group_counts = Counter(
        channel["group"]
        for channel
        in master_channels
    )

    channels_with_fallbacks = sum(
        1
        for channel
        in master_channels
        if channel["fallbacks"]
    )

    total_fallbacks = sum(
        len(
            channel["fallbacks"]
        )
        for channel
        in master_channels
    )


    validation_counter = Counter(
        item["status"]
        for item
        in validation_results
    )


    report.extend(
        [
            "=" * 60,
            "MASTER PLAYLIST SUMMARY",
            "=" * 60,
            "",
            (
                "Total upstream channel entries: "
                f"{total_downloaded}"
            ),
            (
                "Final unique channels: "
                f"{len(master_channels)}"
            ),
            (
                "Alternate feed entries retained: "
                f"{total_fallbacks}"
            ),
            (
                "Channels with at least one fallback: "
                f"{channels_with_fallbacks}"
            ),
            "",
            "Final primary channels by source:",
        ]
    )


    for source in [
        item["short"]
        for item in SOURCES
    ]:

        report.append(
            f"  {source}: "
            f"{source_counts.get(source, 0)}"
        )


    report.extend(
        [
            "",
            "Top categories:",
        ]
    )


    for group, count in (
        group_counts.most_common(40)
    ):

        report.append(
            f"  {group}: {count}"
        )


    report.extend(
        [
            "",
            "=" * 60,
            "SERVER-SIDE VALIDATION SAMPLE",
            "=" * 60,
            "",
            (
                "IMPORTANT: A server-pass does NOT "
                "prove browser/APTV compatibility."
            ),
            (
                "Actual browser playback remains "
                "the final compatibility test."
            ),
            "",
            (
                "Samples tested: "
                f"{len(validation_results)}"
            ),
            (
                "Server pass: "
                f"{validation_counter.get('server-pass', 0)}"
            ),
            (
                "Server warning: "
                f"{validation_counter.get('server-warning', 0)}"
            ),
            (
                "Server fail: "
                f"{validation_counter.get('server-fail', 0)}"
            ),
            "",
        ]
    )


    for item in validation_results:

        report.append(
            f"[{item['status']}] "
            f"{item['source']} - "
            f"{item['name']}"
        )

        report.append(
            f"  {item['reason']}"
        )


    REPORT_FILE.write_text(
        "\n".join(
            report
        )
        + "\n",
        encoding="utf-8",
    )


    print("")
    print(
        "=" * 60
    )

    print(
        "MASTER PLAYLIST V2 COMPLETE"
    )

    print(
        f"Unique channels: "
        f"{len(master_channels)}"
    )

    print(
        f"Alternate feeds retained: "
        f"{total_fallbacks}"
    )

    print(
        f"Validation samples: "
        f"{len(validation_results)}"
    )

    print(
        f"Created: {OUTPUT_FILE}"
    )

    print(
        f"Created: {REPORT_FILE}"
    )

    print(
        f"Created: {TEST_FILE}"
    )

    print(
        f"Created: {SOURCES_FILE}"
    )

    print(
        "=" * 60
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
