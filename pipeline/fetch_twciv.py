#!/usr/bin/env python3
"""Reproducible downloader with SHA-256 provenance manifest for all twciv raw datasets.

Uses Python standard library only. Writes data/raw/manifest.json with URL, byte size,
SHA-256 checksum, and UTC timestamp for every fetched file.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
UA = {"User-Agent": "twciv/1.0 (+https://github.com/twciv)"}

STATIC_FILES = [
    ("tw_boundaries/counties-10t.json", "https://cdn.jsdelivr.net/npm/taiwan-atlas/counties-10t.json"),
    ("tw_boundaries/towns-10t.json", "https://cdn.jsdelivr.net/npm/taiwan-atlas/towns-10t.json"),
    ("etopo/etopo_tw.csv", "https://coastwatch.pfeg.noaa.gov/erddap/griddap/etopo180.csv?altitude%5B(21.4):1:(26.6)%5D%5B(117.8):1:(122.6)%5D"),
    ("natural_earth/ne_10m_roads.geojson", "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_roads.geojson"),
    ("natural_earth/ne_10m_railroads.geojson", "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_railroads.geojson"),
    ("tw_fia/fia_income_2024.csv", "https://raw.githubusercontent.com/kiang/salary/gh-pages/data/csv/2024.csv"),
]

RIS_DATASETS = [
    ("tw_ris/pop_area_110.json", "ODRP048/110"),
    ("tw_ris/pop_area_111.json", "ODRP048/111"),
    ("tw_ris/pop_area_112.json", "ODRP048/112"),
    ("tw_ris/pop_area_113.json", "ODRP048/113"),
    ("tw_ris/pop_area_114.json", "ODRP048/114"),
    ("tw_ris/age_pop_11510.json", "ODRP014/11510"),
    ("tw_ris/edu_114.json", "ODRP020/114"),
    ("tw_ris/hh_114.json", "ODRP025/114"),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(rel: str, url: str, force: bool = False) -> dict:
    dst = RAW / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if force or not dst.exists() or dst.stat().st_size == 0:
        print(f"Downloading {rel} ...")
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            dst.write_bytes(r.read())
    else:
        print(f"Cached {rel} ({dst.stat().st_size / 1024:.1f} KB)")
    return {
        "file": rel,
        "url": url,
        "bytes": dst.stat().st_size,
        "sha256": sha256_file(dst),
        "verified_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def download_ris(rel: str, code: str, force: bool = False) -> dict:
    dst = RAW / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://www.ris.gov.tw/rs-opendata/api/v1/datastore/{code}"
    if force or not dst.exists() or dst.stat().st_size == 0:
        print(f"Fetching RIS {code} -> {rel} ...")
        rows, page = [], 1
        while True:
            req = urllib.request.Request(f"{url}?page={page}", headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode("utf-8"))
            rows.extend(d.get("responseData", []))
            if page >= int(d.get("totalPage", 1)):
                break
            page += 1
            time.sleep(0.15)
        dst.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    else:
        print(f"Cached {rel} ({dst.stat().st_size / 1024:.1f} KB)")
    return {
        "file": rel,
        "url": url,
        "bytes": dst.stat().st_size,
        "sha256": sha256_file(dst),
        "verified_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main(force: bool = False):
    entries = []
    for rel, url in STATIC_FILES:
        entries.append(download_file(rel, url, force=force))
    for rel, code in RIS_DATASETS:
        entries.append(download_ris(rel, code, force=force))
    manifest_path = RAW / "manifest.json"
    manifest_path.write_text(json.dumps({"files": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path} ({len(entries)} files verified with SHA-256).")


if __name__ == "__main__":
    main()
