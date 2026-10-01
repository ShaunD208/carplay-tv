#!/usr/bin/env python3

"""
CarPlay TV Master Playlist Builder v3
=====================================

Target:
    APTV / Apple native HLS / CarPlay

Provider priority:
    1. Samsung TV Plus US
    2. Pluto TV US
    3. Roku
    4. Tubi
    5. Plex US

v3 adds:
- English-focused filtering
- Conservative foreign-language detection
- Provider/source metadata
- Alternate/fallback feed retention
- Known-dead stream rejection
- Fallback promotion when a primary is known dead
- Representative server-side health testing
- Detailed reporting

IMPORTANT:
Server validation does NOT determine browser compatibility.
APTV / Apple native HLS is the authoritative playback target.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path


OUTPUT_FILE = Path("master.m3u")
REPORT_FILE = Path("playlist_report.txt")
TEST_FILE = Path("browser_test_candidates.m3u")
SOURCES_FILE = Path("channel_sources.json")


USER_AGENT = "Mozilla/5.0 CarPlay-TV-Playlist-Builder/3.0"

VALIDATION_TIMEOUT = 12
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


# ------------------------------------------------------------
# LANGUAGE FILTERING
# ------------------------------------------------------------

# Strong category indicators. If one of these appears in the
# provider's group/category, we can safely classify it as
# non-English for this user's playlist.
NON_ENGLISH_GROUP_TERMS = [
    "español",
    "en español",
    "latino",
    "latina",
    "spanish",
    "français",
    "french",
    "português",
    "portuguese",
    "deutsch",
    "german",
    "italiano",
    "italian",
    "한국",
    "korean",
    "日本",
    "japanese",
    "中文",
    "chinese",
    "hindi",
    "punjabi",
    "urdu",
    "arabic",
    "العربية",
    "filipino",
    "tagalog",
    "vietnamese",
    "thai",
]


# Strong name indicators.
#
# Keep this conservative. We do NOT reject a channel simply
# because its title happens to contain a foreign word.
NON_ENGLISH_NAME_PATTERNS = [
    r"\ben español\b",
    r"\bespañol\b",
    r"\bespanol\b",
    r"\bspanish\b",
    r"\ben français\b",
    r"\bfrançais\b",
    r"\bportuguês\b",
    r"\bem português\b",
    r"\bauf deutsch\b",
    r"\bin italiano\b",
    r"\ben hindi\b",
    r"\ben español latino\b",
]


# Some channel names strongly identify Spanish-language feeds
# even when the provider category is poor.
STRONG_SPANISH_FEED_PATTERNS = [
    r"\bnoticias\b",
    r"\bdeportes en español\b",
    r"\bcine en español\b",
    r"\bpelículas en español\b",
    r"\bpeliculas en español\b",
    r"\btelenovelas\b",
    r"\bnovelas\b",
]


# ------------------------------------------------------------
# KNOWN DEAD STREAMS
# ------------------------------------------------------------

# Confirmed both by our server test and actual user playback.
#
# Use normalized channel names.
KNOWN_DEAD_CHANNELS = {
    "unbeatensports",
}


def request_url(
    url: str,
    timeout: int = 60,
    max_bytes: int | None = None,
):
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

    value = name.casefold()

    value = value.replace(
        "&",
        "and",
    )

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


def is_non_english(
    name: str,
    group: str,
) -> tuple[bool, str]:

    """
    Conservative language filtering.

    Returns:
        (should_filter, reason)
    """

    name_lower = name.casefold()
    group_lower = group.casefold()


    for term in NON_ENGLISH_GROUP_TERMS:

        if term.casefold() in group_lower:

            return (
                True,
                f"category '{group}'",
            )


    for pattern in NON_ENGLISH_NAME_PATTERNS:

        if re.search(
            pattern,
            name_lower,
            flags=re.IGNORECASE,
        ):

            return (
                True,
                f"name '{name}'",
            )


    for pattern in STRONG_SPANISH_FEED_PATTERNS:

        if re.search(
            pattern,
            name_lower,
            flags=re.IGNORECASE,
        ):

            return (
                True,
                f"name '{name}'",
            )


    return False, ""


def add_metadata(
    extinf: str,
    source: str,
    fallback_count: int,
) -> str:

    comma_position = extinf.rfind(",")

    if comma_position == -1:
        return extinf

    before_name = extinf[:comma_position]

    channel_name = extinf[
        comma_position:
    ]

    return (
        f'{before_name} '
        f'source="{source}" '
        f'fallbacks="{fallback_count}"'
        f"{channel_name}"
    )


def validate_stream(url: str) -> dict:

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
            or "mpegurl"
            in content_type.casefold()
            or ".m3u8"
            in final_url.casefold()
        )

        result["looks_like_hls"] = (
            looks_like_hls
        )

        if looks_like_hls:

            result["status"] = (
                "server-pass"
            )

            result["reason"] = (
                "Manifest reachable and "
                "appears to be HLS"
            )

        else:

            result["status"] = (
                "server-warning"
            )

            result["reason"] = (
                "URL reachable but response "
                "was not clearly HLS"
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

    by_source = defaultdict(list)

    for channel in channels:

        by_source[
            channel["source"]
        ].append(channel)


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

            selected.append(
                candidates[0]
            )

            continue


        indexes = {
            round(
                i
                * (len(candidates) - 1)
                / (sample_size - 1)
            )
            for i in range(
                sample_size
            )
        }


        for index in sorted(indexes):

            selected.append(
                candidates[index]
            )


    return selected


def rebuild_extinf_for_promoted_feed(
    primary: dict,
    promoted: dict,
) -> str:

    """
    If a fallback is promoted, preserve the original primary's
    metadata where useful but replace fields we know from the
    promoted feed.
    """

    extinf = primary["extinf"]

    if promoted.get("logo"):

        if 'tvg-logo="' in extinf:

            extinf = re.sub(
                r'tvg-logo="[^"]*"',
                (
                    'tvg-logo="'
                    + promoted["logo"]
                    + '"'
                ),
                extinf,
                count=1,
            )


    if promoted.get("tvg_id"):

        if 'tvg-id="' in extinf:

            extinf = re.sub(
                r'tvg-id="[^"]*"',
                (
                    'tvg-id="'
                    + promoted["tvg_id"]
                    + '"'
                ),
                extinf,
                count=1,
            )


    return extinf


def promote_known_dead_primaries(
    channels: list[dict],
) -> list[dict]:

    promoted_count = 0
    removed_count = 0

    result = []

    for channel in channels:

        key = normalize_name(
            channel["name"]
        )

        if key not in KNOWN_DEAD_CHANNELS:

            result.append(channel)
            continue


        if channel["fallbacks"]:

            old_primary = {
                "source": channel["source"],
                "name": channel["name"],
                "url": channel["url"],
                "logo": channel["logo"],
                "group": channel["group"],
                "tvg_id": channel["tvg_id"],
            }

            promoted = (
                channel["fallbacks"].pop(0)
            )

            channel["source"] = (
                promoted["source"]
            )

            channel["url"] = (
                promoted["url"]
            )

            channel["logo"] = (
                promoted.get("logo", "")
                or channel["logo"]
            )

            channel["tvg_id"] = (
                promoted.get("tvg_id", "")
                or channel["tvg_id"]
            )

            channel["extinf"] = (
                rebuild_extinf_for_promoted_feed(
                    channel,
                    promoted,
                )
            )

            # Keep the old feed out of fallbacks because it is
            # already confirmed dead.
            promoted_count += 1

            result.append(channel)

        else:

            removed_count += 1


    return (
        result,
        promoted_count,
        removed_count,
    )


def build_master():

    primary_by_key = {}
    ordered_keys = []

    total_downloaded = 0

    language_filtered = Counter()

    language_examples = defaultdict(list)


    report = [
        "CARPLAY TV MASTER PLAYLIST REPORT V3",
        "=" * 64,
        "",
        "Target: APTV / Apple native HLS / CarPlay",
        "Language preference: English-only",
        "",
    ]


    #
    # DOWNLOAD + LANGUAGE FILTER + DEDUPLICATE
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


        raw_channels = parse_playlist(
            text
        )

        total_downloaded += len(
            raw_channels
        )


        accepted_channels = []

        filtered_here = 0


        for channel in raw_channels:

            filtered, reason = (
                is_non_english(
                    channel["name"],
                    channel["group"],
                )
            )

            if filtered:

                filtered_here += 1

                language_filtered[
                    source_short
                ] += 1

                if (
                    len(
                        language_examples[
                            source_short
                        ]
                    )
                    < 20
                ):

                    language_examples[
                        source_short
                    ].append(
                        (
                            channel["name"],
                            channel["group"],
                            reason,
                        )
                    )

                continue


            accepted_channels.append(
                channel
            )


        added = 0
        duplicate_count = 0


        for channel in accepted_channels:

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

                channel["source"] = (
                    source_short
                )

                channel["fallbacks"] = []

                primary_by_key[key] = (
                    channel
                )

                ordered_keys.append(key)

                added += 1


            else:

                duplicate_count += 1

                primary = (
                    primary_by_key[key]
                )

                existing_urls = {
                    primary["url"]
                }

                existing_urls.update(
                    fallback["url"]
                    for fallback
                    in primary["fallbacks"]
                )

                if (
                    feed["url"]
                    not in existing_urls
                ):

                    primary[
                        "fallbacks"
                    ].append(feed)


        report.extend(
            [
                source_name,
                "-" * len(source_name),
                (
                    "Raw channels: "
                    f"{len(raw_channels)}"
                ),
                (
                    "Non-English filtered: "
                    f"{filtered_here}"
                ),
                (
                    "English candidates: "
                    f"{len(accepted_channels)}"
                ),
                (
                    "New unique channels added: "
                    f"{added}"
                ),
                (
                    "Alternate feeds retained: "
                    f"{duplicate_count}"
                ),
                "",
            ]
        )


        print(
            f"  raw: "
            f"{len(raw_channels)}"
        )

        print(
            f"  language filtered: "
            f"{filtered_here}"
        )

        print(
            f"  unique added: "
            f"{added}"
        )


    master_channels = [
        primary_by_key[key]
        for key in ordered_keys
    ]


    #
    # KNOWN DEAD PRIMARY HANDLING
    #

    (
        master_channels,
        dead_promoted,
        dead_removed,
    ) = promote_known_dead_primaries(
        master_channels
    )


    #
    # VALIDATION SAMPLE
    #

    print("")
    print(
        "Running representative "
        "server-side validation..."
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
                "source": (
                    channel["source"]
                ),
                "name": (
                    channel["name"]
                ),
                "url": (
                    channel["url"]
                ),
                **result,
            }
        )


    #
    # MASTER M3U
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
    # BROWSER/APTV TEST PLAYLIST
    #

    test_lines = [
        "#EXTM3U",
    ]


    validation_names = {
        (
            item["source"],
            item["name"],
        )
        for item in validation_results
    }


    for channel in master_channels:

        if (
            channel["source"],
            channel["name"],
        ) not in validation_names:

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
    # SOURCE / FALLBACK DATABASE
    #

    source_database = []


    for channel in master_channels:

        source_database.append(
            {
                "name": (
                    channel["name"]
                ),
                "normalized_name": (
                    normalize_name(
                        channel["name"]
                    )
                ),
                "group": (
                    channel["group"]
                ),
                "logo": (
                    channel["logo"]
                ),
                "tvg_id": (
                    channel["tvg_id"]
                ),
                "primary": {
                    "source": (
                        channel["source"]
                    ),
                    "url": (
                        channel["url"]
                    ),
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
    # REPORT
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


    total_fallbacks = sum(
        len(
            channel["fallbacks"]
        )
        for channel
        in master_channels
    )


    channels_with_fallbacks = sum(
        1
        for channel
        in master_channels
        if channel["fallbacks"]
    )


    validation_counter = Counter(
        item["status"]
        for item
        in validation_results
    )


    report.extend(
        [
            "=" * 64,
            "LANGUAGE FILTER SUMMARY",
            "=" * 64,
            "",
        ]
    )


    total_language_filtered = sum(
        language_filtered.values()
    )


    report.append(
        "Total non-English entries filtered: "
        f"{total_language_filtered}"
    )

    report.append("")


    for source in [
        item["short"]
        for item in SOURCES
    ]:

        report.append(
            f"{source}: "
            f"{language_filtered.get(source, 0)}"
        )


        examples = (
            language_examples.get(
                source,
                [],
            )
        )


        for (
            name,
            group,
            reason,
        ) in examples:

            report.append(
                f"  FILTERED: {name} "
                f"[{group}] "
                f"because {reason}"
            )


        report.append("")


    report.extend(
        [
            "=" * 64,
            "MASTER PLAYLIST SUMMARY",
            "=" * 64,
            "",
            (
                "Total upstream entries: "
                f"{total_downloaded}"
            ),
            (
                "Non-English entries filtered: "
                f"{total_language_filtered}"
            ),
            (
                "Final unique English-focused channels: "
                f"{len(master_channels)}"
            ),
            (
                "Alternate feeds retained: "
                f"{total_fallbacks}"
            ),
            (
                "Channels with fallback feeds: "
                f"{channels_with_fallbacks}"
            ),
            (
                "Known-dead primaries promoted: "
                f"{dead_promoted}"
            ),
            (
                "Known-dead channels removed: "
                f"{dead_removed}"
            ),
            "",
            "Primary channels by source:",
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
            "=" * 64,
            "SERVER-SIDE VALIDATION SAMPLE",
            "=" * 64,
            "",
            (
                "Target playback environment: "
                "APTV / Apple native HLS."
            ),
            (
                "Server validation is health checking only."
            ),
            (
                "Chrome/hls.js failure does NOT automatically "
                "exclude a channel."
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
        "\n".join(report) + "\n",
        encoding="utf-8",
    )


    print("")
    print(
        "=" * 64
    )

    print(
        "CARPLAY TV MASTER V3 COMPLETE"
    )

    print(
        "Final English-focused channels: "
        f"{len(master_channels)}"
    )

    print(
        "Non-English entries filtered: "
        f"{total_language_filtered}"
    )

    print(
        "Alternate feeds retained: "
        f"{total_fallbacks}"
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
        "=" * 64
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
