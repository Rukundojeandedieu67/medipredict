#!/usr/bin/env python3
"""
MediPredict - download every PUBLIC raw dataset into datasets/raw/.

Place this file at:  ml_engine/scripts/download_datasets.py
Run from repo root:  ml_engine\\.venv\\Scripts\\python ml_engine\\scripts\\download_datasets.py

Standard library only (no pip install needed).

What it fetches (all official/public, nothing synthetic):
  census   NISR Census 2022 district profile PDFs (30 districts)
  dhs      NISR Rwanda DHS 2019-20 report PDF(s)
  rema     District boundaries as GeoJSON from the Rwanda REMA GIS server
  hdx      HDX "Rwanda - Subnational Administrative Boundaries" (COD-AB)
  osm      (opt-in) health facilities from OpenStreetMap via Overpass

What it CANNOT fetch (login/request required) - printed at the end:
  census microdata, DHS microdata, EICV, official Master Facility List.

Every file is recorded in datasets/raw/MANIFEST.json and SOURCES_AUTO.md
with URL, access date, size and SHA-256 so provenance is provable.

Usage:
  python download_datasets.py                 # census, dhs, rema, hdx
  python download_datasets.py --only census   # one or more, comma separated
  python download_datasets.py --only osm      # OpenStreetMap facilities
  python download_datasets.py --force         # re-download existing files
  python download_datasets.py --out D:\\data\\raw
"""
import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

UA = "Mozilla/5.0 (compatible; MediPredict-hackathon-data-fetch/1.0)"
PAUSE = 0.6  # seconds between requests, be polite to government servers

DISTRICTS = {
    "Kigali City": ["Nyarugenge", "Gasabo", "Kicukiro"],
    "Southern": ["Nyanza", "Gisagara", "Nyaruguru", "Huye", "Nyamagabe",
                 "Ruhango", "Muhanga", "Kamonyi"],
    "Western": ["Karongi", "Rutsiro", "Rubavu", "Nyabihu", "Ngororero",
                "Rusizi", "Nyamasheke"],
    "Northern": ["Rulindo", "Gakenke", "Musanze", "Burera", "Gicumbi"],
    "Eastern": ["Rwamagana", "Nyagatare", "Gatsibo", "Kayonza", "Kirehe",
                "Ngoma", "Bugesera"],
}
ALL_DISTRICTS = [d for ds in DISTRICTS.values() for d in ds]

CENSUS_LIST = ("https://statistics.gov.rw/datasource/"
               "fifth-population-and-housing-census-2022")
DHS_PAGE = ("https://statistics.gov.rw/data-sources/surveys/"
            "Demographic-and-Health-Survey/demographic-and-health-survey-201920")
REMA_DISTRICT = ("https://gis.rema.gov.rw/server/rest/services/"
                 "pollution/District/MapServer")
HDX_API = "https://data.humdata.org/api/3/action/package_search"
OVERPASS = "https://overpass-api.de/api/interpreter"

MANIFEST = []


# ----------------------------------------------------------------- helpers
def http_get(url, data=None, retries=3, timeout=90):
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            time.sleep(2 * attempt)
    raise RuntimeError(f"GET failed after {retries} tries: {url} ({last})")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self._href, self._text = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, d):
        if self._href is not None:
            self._text.append(d)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = " ".join("".join(self._text).split())
            self.links.append((self._href, text))
            self._href = None


def get_links(url):
    """Return [(absolute_url, link_text)] for every <a> on the page."""
    html = http_get(url).decode("utf-8", errors="replace")
    p = _Links()
    p.feed(html)
    time.sleep(PAUSE)
    return [(urllib.parse.urljoin(url, h), t) for h, t in p.links if h]


def is_pdf(href):
    path = urllib.parse.urlparse(href).path.lower()
    return path.endswith(".pdf") and "/print/pdf/" not in path


def save(url, dest, source, note="", force=False, data=None):
    """Download url -> dest (skip if exists). Records provenance."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        print(f"  skip (exists)  {dest.name}")
        body = dest.read_bytes()
        status = "already_present"
    else:
        body = http_get(url, data=data)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(body)
        tmp.replace(dest)
        status = "downloaded"
        print(f"  ok  {dest.name}  ({len(body)/1024:.0f} KB)")
        time.sleep(PAUSE)
    MANIFEST.append({
        "file": str(dest),
        "source": source,
        "url": url,
        "note": note,
        "status": status,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "accessed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    })
    return dest


def find_district(*texts):
    blob = " ".join(texts).lower()
    for d in ALL_DISTRICTS:
        if d.lower() in blob:
            return d
    return None


# ------------------------------------------------------------------- steps
def step_census(out, force):
    print("\n[census] NISR Census 2022 district profiles")
    folder = out / "nisr_census_2022_district_profiles"
    pages = {}  # profile page url -> link text
    for n in range(0, 10):
        try:
            links = get_links(f"{CENSUS_LIST}?page={n}")
        except RuntimeError as e:
            print("  listing failed:", e)
            break
        new = 0
        for href, text in links:
            if "district profile" in text.lower() and href not in pages:
                pages[href] = text
                new += 1
        if new == 0 and n > 0:
            break
    print(f"  found {len(pages)} district-profile pages")

    got = {}
    for page_url, text in pages.items():
        try:
            pdfs = [page_url] if is_pdf(page_url) else [
                h for h, _ in get_links(page_url) if is_pdf(h)]
        except RuntimeError as e:
            print("  page failed:", page_url, e)
            continue
        for pdf in pdfs[:1]:
            name = urllib.parse.unquote(Path(urllib.parse.urlparse(pdf).path).name)
            d = find_district(text, name, page_url)
            fname = f"census2022_district_profile_{d}.pdf" if d else name
            try:
                save(pdf, folder / fname, "NISR RPHC5 District Profile",
                     note=text, force=force)
                if d:
                    got[d] = True
            except RuntimeError as e:
                print("  download failed:", e)

    missing = [d for d in ALL_DISTRICTS if d not in got]
    if missing:
        print(f"  WARNING: {len(missing)} districts not found: {', '.join(missing)}")
        print("  -> download them by hand from", CENSUS_LIST)
    else:
        print("  all 30 districts present")


def step_dhs(out, force):
    print("\n[dhs] NISR DHS 2019-20 report")
    folder = out / "nisr_dhs_2019_20"
    pdfs = [(h, t) for h, t in get_links(DHS_PAGE) if is_pdf(h)]
    if not pdfs:
        print("  no PDF link found on page; get the Final Report manually from")
        print("  ", DHS_PAGE)
        return
    for href, text in pdfs[:5]:
        name = urllib.parse.unquote(Path(urllib.parse.urlparse(href).path).name)
        save(href, folder / name, "NISR RDHS 2019-20", note=text, force=force)


def step_rema(out, force):
    print("\n[rema] District boundaries (REMA GIS server)")
    meta = json.loads(http_get(REMA_DISTRICT + "?f=pjson"))
    layers = meta.get("layers") or []
    lid = layers[0]["id"] if layers else 0
    q = urllib.parse.urlencode({
        "where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson"})
    url = f"{REMA_DISTRICT}/{lid}/query?{q}"
    dest = save(url, out / "boundaries" / "rema_district_boundaries.geojson",
                "REMA/RNRA via gis.rema.gov.rw (2006, updated 2012)",
                note=f"layer {lid}", force=force)
    try:
        n = len(json.loads(dest.read_text(encoding="utf-8")).get("features", []))
        print(f"  features: {n} (expect 30)")
    except Exception as e:
        print("  could not validate GeoJSON:", e)


def step_hdx(out, force):
    print("\n[hdx] COD-AB subnational boundaries")
    q = urllib.parse.urlencode({
        "q": "Rwanda Subnational Administrative Boundaries", "rows": 10})
    res = json.loads(http_get(f"{HDX_API}?{q}"))
    pkgs = res.get("result", {}).get("results", [])
    pick = next((p for p in pkgs
                 if "rwanda" in p.get("title", "").lower()
                 and "boundar" in p.get("title", "").lower()), None)
    if not pick:
        print("  dataset not found via API; download manually from data.humdata.org")
        return
    print("  dataset:", pick["title"])
    wanted = [r for r in pick.get("resources", [])
              if r.get("format", "").lower() in ("shp", "geojson")][:2]
    if not wanted:
        print("  no SHP/GeoJSON resource listed; open the dataset page by hand")
        return
    for r in wanted:
        url = r.get("download_url") or r.get("url")
        name = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)
        save(url, out / "boundaries" / f"hdx_{name}",
             "HDX COD-AB Rwanda (source: NISR)", note=pick["title"], force=force)


def step_osm(out, force):
    print("\n[osm] Health facilities from OpenStreetMap (Overpass)")
    print("  NOTE: OSM is community-mapped and incomplete. It is NOT the")
    print("  official facility registry. Label it as such in your docs.")
    query = (
        '[out:json][timeout:180];'
        'area["ISO3166-1"="RW"][admin_level=2]->.a;'
        '(nwr["amenity"~"^(hospital|clinic|doctors)$"](area.a);'
        'nwr["healthcare"](area.a););'
        'out center tags;'
    )
    data = urllib.parse.urlencode({"data": query}).encode()
    save(OVERPASS, out / "facilities" / "osm_rwanda_health_facilities.json",
         "OpenStreetMap contributors (ODbL) via Overpass API",
         note="amenity=hospital|clinic|doctors or healthcare=*", force=force,
         data=data)


STEPS = {"census": step_census, "dhs": step_dhs, "rema": step_rema,
         "hdx": step_hdx, "osm": step_osm}
DEFAULT = ["census", "dhs", "rema", "hdx"]

MANUAL = """
MANUAL DOWNLOADS (need login or a data request - not scriptable):
  1. Census 2022 microdata (free account)
       https://microdata.statistics.gov.rw/index.php/catalog/109
  2. DHS 2019-20 microdata (free account)
       https://microdata.statistics.gov.rw/index.php/catalog/98
  3. EICV poverty report: latest on https://statistics.gov.rw (check that it
     has district-level poverty headcount before using it as a feature)
  4. Official Master Facility List with coordinates: request from the
     Ministry of Health / hackathon organisers. Do NOT use the 5-row sample
     at docs.nhic.moh.gov.rw - it is a documentation example, not real data.
  5. Real stock/consumption logs (eLMIS/HMIS): organisers only. Until then
     stock data stays in datasets/synthetic with is_synthetic=true.
Put manual downloads in datasets/raw/<source_name>/ and add a line to
SOURCES.md (publisher, URL, access date, licence).
"""


def write_manifest(out):
    out.mkdir(parents=True, exist_ok=True)
    mpath = out / "MANIFEST.json"
    old = []
    if mpath.exists():
        try:
            old = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            old = []
    merged = {m["file"]: m for m in old}
    merged.update({m["file"]: m for m in MANIFEST})
    rows = sorted(merged.values(), key=lambda m: m["file"])
    mpath.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    lines = ["# Auto-generated download log (do not hand-edit)\n",
             "| file | source | accessed (UTC) | KB | sha256 (first 12) |",
             "|---|---|---|---|---|"]
    for m in rows:
        rel = Path(m["file"]).name
        lines.append(f"| {rel} | {m['source']} | {m['accessed_utc']} | "
                     f"{m['bytes']/1024:.0f} | {m['sha256'][:12]} |")
    (out / "SOURCES_AUTO.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma list of: " + ",".join(STEPS))
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    ap.add_argument("--out", help="output dir (default: <repo>/datasets/raw)")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[2]  # ml_engine/scripts/ -> repo root
    out = Path(args.out) if args.out else repo / "datasets" / "raw"
    wanted = args.only.split(",") if args.only else DEFAULT
    bad = [w for w in wanted if w not in STEPS]
    if bad:
        sys.exit(f"unknown step(s): {bad}. choose from {list(STEPS)}")

    print("Output folder:", out)
    failed = []
    for name in wanted:
        try:
            STEPS[name](out, args.force)
        except Exception as e:  # keep going; one dead source must not stop the rest
            failed.append(name)
            print(f"  [{name}] FAILED: {e}")

    write_manifest(out)
    print("\nDone. Files recorded in", out / "MANIFEST.json")
    if failed:
        print("Failed steps (re-run with --only):", ", ".join(failed))
    print(MANUAL)


if __name__ == "__main__":
    main()