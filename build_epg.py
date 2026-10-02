#!/usr/bin/env python3
"""Build a compact EPG for the CarPlay TV master player.

Downloads the official guide sources referenced by the upstream FAST playlists,
keeps only channels present in channel_sources.json, and writes a rolling schedule
window to epg.json. The browser resolves Now/Next locally so guide data remains
useful throughout the day rather than being frozen at workflow build time.
"""

from __future__ import annotations

import gzip
import io
import json
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_FILE = Path("channel_sources.json")
OUT_FILE = Path("epg.json")
REPORT_FILE = Path("playlist_report.txt")
USER_AGENT = "Mozilla/5.0 CarPlay-TV-EPG-Builder/1.0"

GUIDES = {
    "Samsung": "https://github.com/matthuisman/i.mjh.nz/raw/master/SamsungTVPlus/us.xml.gz",
    "Pluto": "https://github.com/matthuisman/i.mjh.nz/raw/master/PlutoTV/us.xml.gz",
    "Roku": "https://github.com/matthuisman/i.mjh.nz/raw/master/Roku/all.xml.gz",
    "Tubi": "https://raw.githubusercontent.com/BuddyChewChew/app-m3u-generator/main/playlists/tubi_epg.xml",
    "Plex": "https://github.com/matthuisman/i.mjh.nz/raw/master/Plex/us.xml.gz",
}


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=90) as response:
        data = response.read()
    if url.lower().endswith(".gz"):
        return gzip.decompress(data)
    return data


def parse_xmltv_time(value: str) -> datetime | None:
    if not value:
        return None
    # XMLTV normally uses YYYYMMDDHHMMSS +ZZZZ; tolerate missing seconds/zone.
    base = value.strip()
    for fmt in ("%Y%m%d%H%M%S %z", "%Y%m%d%H%M %z", "%Y%m%d%H%M%S", "%Y%m%d%H%M"):
        try:
            dt = datetime.strptime(base, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    return None


def text_of(element: ET.Element, tag: str) -> str:
    child = element.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def main() -> None:
    database = json.loads(DB_FILE.read_text(encoding="utf-8"))

    # Build source -> tvg-id set, and remember each master channel's candidate IDs
    # in provider-priority order (primary first, then fallbacks).
    wanted_by_source: dict[str, set[str]] = defaultdict(set)
    candidates_by_name: dict[str, list[tuple[str, str]]] = {}

    for item in database:
        candidates: list[tuple[str, str]] = []
        primary_source = (item.get("primary") or {}).get("source", "")
        primary_id = str(item.get("tvg_id") or "").strip()
        if primary_source and primary_id:
            candidates.append((primary_source, primary_id))
            wanted_by_source[primary_source].add(primary_id)

        for fallback in item.get("fallbacks", []):
            source = str(fallback.get("source") or "").strip()
            tvg_id = str(fallback.get("tvg_id") or "").strip()
            if source and tvg_id and (source, tvg_id) not in candidates:
                candidates.append((source, tvg_id))
                wanted_by_source[source].add(tvg_id)

        candidates_by_name[item["name"]] = candidates

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=3)
    window_end = now + timedelta(hours=36)
    programmes: dict[tuple[str, str], list[dict]] = defaultdict(list)
    guide_stats = {}

    for source, url in GUIDES.items():
        wanted = wanted_by_source.get(source, set())
        if not wanted:
            continue
        print(f"Downloading {source} EPG ({len(wanted)} wanted IDs)...")
        try:
            xml_bytes = download(url)
            matched_programmes = 0
            matched_channels = set()
            # iterparse avoids constructing a second large in-memory representation.
            for _, elem in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
                if elem.tag != "programme":
                    continue
                channel_id = str(elem.attrib.get("channel") or "")
                if channel_id not in wanted:
                    elem.clear()
                    continue
                start = parse_xmltv_time(elem.attrib.get("start", ""))
                stop = parse_xmltv_time(elem.attrib.get("stop", ""))
                if not start or not stop or stop < window_start or start > window_end:
                    elem.clear()
                    continue
                title = text_of(elem, "title") or "Program information unavailable"
                subtitle = text_of(elem, "sub-title")
                desc = text_of(elem, "desc")
                programmes[(source, channel_id)].append({
                    "s": int(start.timestamp()),
                    "e": int(stop.timestamp()),
                    "t": title,
                    **({"st": subtitle} if subtitle else {}),
                    **({"d": desc[:500]} if desc else {}),
                })
                matched_programmes += 1
                matched_channels.add(channel_id)
                elem.clear()
            guide_stats[source] = {
                "wanted_ids": len(wanted),
                "matched_ids": len(matched_channels),
                "programmes": matched_programmes,
            }
        except Exception as exc:
            print(f"WARNING: {source} EPG failed: {exc}")
            guide_stats[source] = {"wanted_ids": len(wanted), "matched_ids": 0, "programmes": 0, "error": str(exc)}

    output_channels = {}
    fallback_epg_used = 0
    no_epg = []

    for name, candidates in candidates_by_name.items():
        chosen = None
        chosen_programmes = None
        for index, candidate in enumerate(candidates):
            items = programmes.get(candidate)
            if items:
                chosen = candidate
                chosen_programmes = sorted(items, key=lambda p: p["s"])
                if index > 0:
                    fallback_epg_used += 1
                break
        if chosen and chosen_programmes:
            output_channels[name] = {
                "source": chosen[0],
                "id": chosen[1],
                "programmes": chosen_programmes,
            }
        else:
            no_epg.append(name)

    payload = {
        "generated": int(now.timestamp()),
        "window_end": int(window_end.timestamp()),
        "channels": output_channels,
    }
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    report = REPORT_FILE.read_text(encoding="utf-8") if REPORT_FILE.exists() else ""
    marker = "\n================================================================\nEPG / NOW PLAYING SUMMARY\n"
    if marker in report:
        report = report.split(marker, 1)[0].rstrip() + "\n"
    report += marker
    report += "================================================================\n\n"
    report += f"Master channels: {len(database)}\n"
    report += f"Channels with guide data: {len(output_channels)}\n"
    report += f"Channels without guide data: {len(no_epg)}\n"
    report += f"Channels using fallback-provider guide identity: {fallback_epg_used}\n"
    report += "Guide window: 3 hours past through 36 hours future\n\n"
    for source in GUIDES:
        stat = guide_stats.get(source)
        if not stat:
            continue
        report += f"{source}: {stat['matched_ids']}/{stat['wanted_ids']} IDs matched; {stat['programmes']} programmes"
        if stat.get("error"):
            report += f"; ERROR: {stat['error']}"
        report += "\n"
    if no_epg:
        report += "\nSample channels without guide data:\n"
        for name in no_epg[:40]:
            report += f"  {name}\n"
    REPORT_FILE.write_text(report, encoding="utf-8")

    print(f"EPG complete: {len(output_channels)}/{len(database)} channels with guide data")
    print(f"Fallback-provider EPG identities used: {fallback_epg_used}")
    print(f"Created: {OUT_FILE}")


if __name__ == "__main__":
    main()
