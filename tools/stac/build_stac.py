"""Build the static STAC catalog in <repo>/stac/ (self-contained, relative links).

Phase 1  extract per-file metadata (+ thumbnails for license_tier == "open"), cached in catalog/cache/
Phase 2  assemble Collections (one per upstream source), Items, and dimension "views" catalogs
Phase 3  write items.parquet (flat, for DuckDB/pandas) and validate

Usage: tools/.venv/bin/python -I tools/stac/build_stac.py [--no-thumbs] [--workers N]
"""
import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import extract  # noqa: E402
import items as itemspec  # noqa: E402
from sources import LICENSE_SURVEY, RETRIEVED, SOURCES  # noqa: E402

ROOT = HERE.parents[1]
OUT = ROOT / "stac"
CACHE = ROOT / "catalog/cache"
PY = sys.executable
CATALOG_ID = "bim-test-data"
NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
STAC_VERSION = "1.1.0"
EXT_FILE = "https://stac-extensions.github.io/file/v2.1.0/schema.json"
EXT_SCI = "https://stac-extensions.github.io/scientific/v1.0.0/schema.json"
THUMB_MAX_BYTES = 80_000_000
THUMB_TIMEOUT = 420


# ============================================================================ phase 1
def _cache_key(p: Path) -> str:
    st = p.stat()
    return hashlib.sha1(f"{p}|{st.st_size}|{st.st_mtime_ns}|v3".encode()).hexdigest()


def extract_asset(local: str, want_thumb: bool, thumb_out: str) -> dict:
    p = Path(local)
    key = _cache_key(p)
    cf = CACHE / f"{key}.json"
    if cf.exists():
        meta = json.loads(cf.read_text())
    else:
        meta = {"_file": extract.file_info(p)}
        try:
            meta.update(extract.zip_listing(p) if p.suffix.lower() == ".zip" else extract.extract(p))
        except Exception as e:  # noqa: BLE001
            meta["bim:extract_error"] = f"{type(e).__name__}: {str(e)[:160]}"
        if isinstance(meta.get("_datetime"), dt.datetime):
            meta["_datetime"] = meta["_datetime"].isoformat()
        cf.write_text(json.dumps(meta, default=str, ensure_ascii=False))
    if want_thumb:
        tcache = CACHE / f"{key}.png"
        terr = CACHE / f"{key}.thumberr"
        if not tcache.exists() and not terr.exists():
            if p.stat().st_size > THUMB_MAX_BYTES:
                terr.write_text("skipped: file larger than thumbnail limit")
            else:
                try:
                    r = subprocess.run([PY, "-I", str(HERE / "thumbs.py"), str(p), str(tcache)], capture_output=True, text=True, timeout=THUMB_TIMEOUT)
                    if r.returncode != 0 or not tcache.exists():
                        terr.write_text((r.stderr or r.stdout)[-400:])
                except subprocess.TimeoutExpired:
                    terr.write_text("timeout")
        if tcache.exists():
            Path(thumb_out).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tcache, thumb_out)
            meta["_thumb"] = thumb_out
        elif terr.exists():
            meta["_thumb_error"] = ([l.strip() for l in terr.read_text().splitlines() if l.strip()] or ["unknown"])[-1][:200]  # last line only, no local paths
    return meta


# ============================================================================ phase 2 helpers
def size_class(n):
    return "xs(<100KB)" if n < 1e5 else "s(<1MB)" if n < 1e6 else "m(<20MB)" if n < 2e7 else "l(<100MB)" if n < 1e8 else "xl(>=100MB)"


def fmt_version(m):
    f = m.get("bim:format")
    if f in ("IFC-SPF", "IFC-ZIP", "IFC-XML", "IFCX"):
        return m.get("ifc:schema")
    if f in ("DWG", "DXF"):
        return f"{m.get('cad:version_code')} {m.get('cad:release') or ''}".strip() if m.get("cad:version_code") else None
    if f == "RVT":
        return f"Revit {m['rvt:revit_version']}" if m.get("rvt:revit_version") else None
    if f == "JWW":
        return f"JWW v{m['cad:version_code']}" if m.get("cad:version_code") else None
    if f == "PDF":
        return m.get("pdf:version")
    if f == "BCF":
        return f"BCF {m['bcf:version']}" if m.get("bcf:version") else None
    if f == "IDS":
        return "IDS 1.0" if "standards.buildingsmart.org/IDS" in (m.get("ids:namespace") or "") else m.get("ids:namespace")
    if f == "SXF":
        return f"SXF {m.get('cad:sxf_flavour')}"
    if f == "XLSX":
        return "COBie 2.4" if m.get("xlsx:cobie") else None
    return None


FMT_FROM_EXT = {".ifc": "IFC-SPF", ".ifczip": "IFC-ZIP", ".ifcxml": "IFC-XML", ".ifcx": "IFCX", ".dwg": "DWG", ".dxf": "DXF", ".dxfb": "DXF",
                ".pdf": "PDF", ".rvt": "RVT", ".jww": "JWW", ".sfc": "SXF", ".ids": "IDS", ".bcf": "BCF", ".bcfzip": "BCF",
                ".xlsx": "XLSX", ".zip": "ZIP"}
FAMILY = {"IFC-SPF": "IFC", "IFC-ZIP": "IFC", "IFC-XML": "IFC", "IFCX": "IFC", "DWG": "CAD-2D", "DXF": "CAD-2D", "JWW": "CAD-2D",
          "SXF": "CAD-2D", "ZIP": "CAD-2D", "PDF": "PDF", "RVT": "BIM-native", "IDS": "openBIM-exchange", "BCF": "openBIM-exchange", "XLSX": "COBie"}


def parse_dt(s):
    if not s:
        return None
    if isinstance(s, dt.datetime):
        return s
    s = str(s).strip().replace("/", "-")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            d = dt.datetime.strptime(s[:25] if "%z" in fmt else s[:19], fmt)
            d = d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
            d = d.astimezone(dt.timezone.utc)
            return d if 1990 <= d.year <= NOW.year else None
        except ValueError:
            continue
    return None


def rel(a: Path, b: Path) -> str:
    """Relative href from directory of file a to file b."""
    import os
    return os.path.relpath(b, a.parent).replace("\\", "/")


def provenance(spec, asset, src):
    o = src["origin"]
    pv = {"upstream_href": asset["href"], "retrieved": RETRIEVED, "rehosted": False}
    if o["kind"] == "git" or "githubusercontent.com" in asset["href"]:
        parts = asset["href"].split("/")
        repo = "/".join(parts[4:6]) if "media.githubusercontent.com" in asset["href"] else "/".join(parts[3:5])
        commit = parts[6] if "media.githubusercontent.com" in asset["href"] else parts[5]
        path = "/".join(parts[7:] if "media.githubusercontent.com" in asset["href"] else parts[6:])
        import urllib.parse
        pv.update(repository=f"https://github.com/{repo}", commit=commit, path=urllib.parse.unquote(path),
                  browse_url=f"https://github.com/{repo}/blob/{commit}/{path}", git_lfs="media.githubusercontent.com" in asset["href"])
        if o.get("commit_date") and o.get("repo") == repo:
            pv["commit_date"] = o["commit_date"]
    if "web.archive.org" in asset["href"]:
        pv["note"] = "File no longer served by the original host; link points to the Internet Archive capture that was downloaded."
    if asset.get("archive_member"):
        pv["archive_member"] = asset["archive_member"]
    return pv


# ============================================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-thumbs", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        for sub in ("collections", "views"):
            shutil.rmtree(OUT / sub, ignore_errors=True)
    OUT.mkdir(exist_ok=True)

    # ---- phase 1
    jobs = {}
    for spec in itemspec.SPECS:
        src = SOURCES[spec["source"]]
        idir = OUT / "collections" / spec["source"] / "items" / spec["id"]
        for i, a in enumerate(spec["assets"]):
            thumb_ok = (src["tier"] == "open" and not args.no_thumbs and i == 0 and
                        Path(a["local"]).suffix.lower() in (".pdf", ".ifc", ".dwg", ".dxf", ".dxfb"))
            # VA DWG sets: thumbnail from the companion PDF instead of the zip
            if src["tier"] == "open" and not args.no_thumbs and a["key"] == "pdf":
                thumb_ok = True
            jobs[(spec["id"], a["key"])] = (str(a["local"]), thumb_ok, str(idir / "thumbnail.png"))
    results = {}
    print(f"phase 1: {len(jobs)} assets", flush=True)
    with ProcessPoolExecutor(args.workers) as ex:
        futs = {ex.submit(extract_asset, *v): k for k, v in jobs.items()}
        for n, fut in enumerate(as_completed(futs), 1):
            k = futs[fut]
            try:
                results[k] = fut.result()
            except Exception as e:  # noqa: BLE001
                results[k] = {"bim:extract_error": f"{type(e).__name__}: {e}"}
            if n % 50 == 0:
                print(f"  {n}/{len(jobs)}", flush=True)

    # archive (zip) size/checksum for archive-member assets
    zip_info = {}
    for spec in itemspec.SPECS:
        a = spec["assets"][0]
        if a.get("archive_member"):
            zname = a["href"].rsplit("/", 1)[-1]
            zp = ROOT / "raw" / SOURCES[spec["source"]]["origin"]["raw_dir"] / zname
            if zp.exists() and zname not in zip_info:
                zip_info[zname] = extract.file_info(zp)

    # ---- phase 2
    project_members = defaultdict(list)
    for spec in itemspec.SPECS:
        if spec["project"]:
            project_members[spec["project"]].append(spec["id"])

    items_by_coll = defaultdict(list)
    flat_rows = []
    for spec in itemspec.SPECS:
        src = SOURCES[spec["source"]]
        primary = spec["assets"][0]
        m = dict(results[(spec["id"], primary["key"])])
        fileinfo = m.pop("_file", {})
        geo = m.pop("_geometry", None)
        thumb = m.pop("_thumb", None)
        thumb_err = m.pop("_thumb_error", None)
        pdt = m.pop("_datetime", None)
        local = Path(primary["local"])
        fmt = m.get("bim:format") or FMT_FROM_EXT.get(local.suffix.lower(), local.suffix.upper().strip("."))
        if primary.get("archive_member") is None and local.suffix.lower() == ".zip":
            fmt = "ZIP"
        m["bim:format"] = fmt
        tags = {k: v for k, v in spec["tags"].items() if v not in (None, [], "")}
        disciplines = tags.pop("disciplines", None) or m.get("ifc:disciplines") or []
        # datetime
        dtv, dts = None, None
        for cand, label in ((m.get("ifc:header_timestamp"), "IFC header FILE_NAME.time_stamp"), (pdt, "PDF CreationDate")):
            d = parse_dt(cand)
            if d:
                dtv, dts = d, label
                break
        if dtv is None:
            d = parse_dt(src["origin"].get("commit_date"))
            dtv, dts = (d, "upstream repository commit date") if d else (parse_dt(RETRIEVED), "retrieval date")
        item_dir = OUT / "collections" / spec["source"] / "items" / spec["id"]
        item_path = item_dir / f"{spec['id']}.json"
        coll_path = OUT / "collections" / spec["source"] / "collection.json"

        props = {
            "title": spec["title"],
            "description": f"{fmt}{' ' + fmt_version(m) if fmt_version(m) else ''} file from '{src['title']}'. "
                           f"Data is not re-hosted: the asset links to the upstream download location.",
            "datetime": dtv.isoformat().replace("+00:00", "Z"),
            "created": NOW.isoformat().replace("+00:00", "Z"), "updated": NOW.isoformat().replace("+00:00", "Z"),
            "license": src["license"][0] if " " not in src["license"][0] else "other",
            "keywords": sorted(set(src.get("keywords", [])) | set(tags.get("use_cases", []))),
            "providers": src["providers"],
            "bim:format": fmt, "bim:format_family": FAMILY.get(fmt, "other"), "bim:format_version": fmt_version(m),
            "bim:source": spec["source"], "bim:project": spec["project"],
            "bim:building_type": tags.pop("building_type", None), "bim:country": tags.pop("country", None),
            "bim:disciplines": sorted(set(disciplines)), "bim:use_cases": tags.pop("use_cases", []),
            "bim:license_tier": src["tier"], "bim:license_url": src["license"][1], "bim:attribution": src["attribution"],
            "bim:size_class": size_class(fileinfo.get("file:size", 0)),
            "bim:datetime_source": dts, "bim:provenance": provenance(spec, primary, src),
            "bim:thumbnail": "generated" if thumb else ("not generated: license does not allow derivatives/redistribution" if src["tier"] != "open"
                                                        else f"not generated: {thumb_err}" if thumb_err else "not applicable"),
        }
        if "rule" in tags:
            props["bim:validation_rule"] = tags.pop("rule")
            props["bim:validation_expected"] = tags.pop("expected")
        if "csi_division" in tags:
            props["bim:csi_division"] = tags.pop("csi_division")
        if src.get("doi"):
            props["sci:doi"] = src["doi"]
            props["sci:citation"] = src["attribution"]
        props.update({k: v for k, v in m.items() if not k.startswith("_")})
        props = {k: v for k, v in props.items() if v not in (None, [], {}, "")}

        geometry, bbox = None, None
        default = _default_location(geo) if geo and geo.get("status") == "ok" else None
        if default:
            props["bim:site_location_raw"] = [geo["lon"], geo["lat"]]
            props["bim:location_source"] = f"IfcSite location is a software/test default ({default}); geometry left null"
        elif geo and geo.get("status") == "ok":
            geometry = {"type": "Point", "coordinates": [geo["lon"], geo["lat"]]}
            bbox = [geo["lon"], geo["lat"], geo["lon"], geo["lat"]]
            props["bim:location_source"] = "IfcSite.RefLatitude/RefLongitude (as authored; not verified)"
            if geo.get("elevation") is not None:
                props["bim:site_elevation"] = geo["elevation"]
        elif geo:
            props["bim:location_source"] = f"IfcSite location {geo['status']} (geometry left null)"

        assets = {}
        for a in spec["assets"]:
            am = results[(spec["id"], a["key"])]
            fi = am.get("_file", {})
            asset = {"href": a["href"], "type": a["media_type"], "roles": a["roles"], "title": a.get("title")}
            if a.get("archive_member"):
                zname = a["href"].rsplit("/", 1)[-1]
                asset.update(zip_info.get(zname, {}))
                asset["bim:archive_member"] = a["archive_member"]
                asset["bim:archive_member_type"] = a.get("member_media_type")
                asset["bim:archive_member_size"] = fi.get("file:size")
                asset["bim:archive_member_checksum"] = fi.get("file:checksum")
            else:
                asset.update(fi)
            if a["key"] != primary["key"]:
                for k in ("pdf:pages", "pdf:page_sizes"):
                    if k in am:
                        asset[k] = am[k]
            assets[a["key"]] = {k: v for k, v in asset.items() if v is not None}
        # VA sets: thumbnail comes from the companion pdf asset
        if not thumb:
            for a in spec["assets"][1:]:
                t = results[(spec["id"], a["key"])].get("_thumb")
                if t:
                    thumb = t
                    props["bim:thumbnail"] = f"generated from asset '{a['key']}'"
        if thumb:
            assets["thumbnail"] = {"href": "./thumbnail.png", "type": "image/png", "roles": ["thumbnail"],
                                   "title": "Preview (derived; same license as the source data)"}

        links = [
            {"rel": "root", "href": rel(item_path, OUT / "catalog.json"), "type": "application/json"},
            {"rel": "parent", "href": rel(item_path, coll_path), "type": "application/json"},
            {"rel": "collection", "href": rel(item_path, coll_path), "type": "application/json"},
            {"rel": "self", "href": f"./{spec['id']}.json", "type": "application/geo+json"},
            {"rel": "license", "href": src["license"][1], "title": src["license"][0]},
            {"rel": "via", "href": src["homepage"], "title": "Upstream dataset page"},
        ]
        if props["bim:provenance"].get("browse_url"):
            links.append({"rel": "via", "href": props["bim:provenance"]["browse_url"], "title": "Upstream file (pinned commit)"})
        if src.get("doi"):
            links.append({"rel": "cite-as", "href": f"https://doi.org/{src['doi']}"})
        for other in project_members.get(spec["project"], [])[:60]:
            if other != spec["id"]:
                osrc = next(s["source"] for s in itemspec.SPECS if s["id"] == other)
                links.append({"rel": "related", "href": rel(item_path, OUT / "collections" / osrc / "items" / other / f"{other}.json"),
                              "type": "application/geo+json", "title": f"Same project ({spec['project']})"})
        exts = [EXT_FILE] + ([EXT_SCI] if src.get("doi") else [])
        item = {"type": "Feature", "stac_version": STAC_VERSION, "stac_extensions": exts, "id": spec["id"],
                "geometry": geometry, **({"bbox": bbox} if bbox else {}), "properties": props, "links": links,
                "assets": assets, "collection": spec["source"]}
        item_dir.mkdir(parents=True, exist_ok=True)
        item_path.write_text(json.dumps(item, ensure_ascii=False, indent=1, default=str))
        items_by_coll[spec["source"]].append((item, item_path))
        flat_rows.append(_flat(item, item_path))

    for r in itemspec.REMOTE:  # remote-only zip datasets
        src = SOURCES[r["source"]]
        item_dir = OUT / "collections" / r["source"] / "items" / r["id"]
        item_path = item_dir / f"{r['id']}.json"
        coll_path = OUT / "collections" / r["source"] / "collection.json"
        props = {"title": r["title"], "description": f"Archive of IFC models from '{src['title']}' (not downloaded or analysed here).",
                 "datetime": "2026-04-24T00:00:00Z", "created": NOW.isoformat().replace("+00:00", "Z"), "license": src["license"][0],
                 "providers": src["providers"], "keywords": src["keywords"], "bim:format": "ZIP", "bim:format_family": "IFC",
                 "bim:source": r["source"], "bim:building_type": r["tags"]["building_type"], "bim:country": r["tags"]["country"],
                 "bim:use_cases": r["tags"]["use_cases"], "bim:license_tier": src["tier"], "bim:license_url": src["license"][1],
                 "bim:attribution": src["attribution"], "bim:size_class": size_class(r["size"]), "bim:datetime_source": "Zenodo publication date",
                 "bim:provenance": {"upstream_href": r["href"], "retrieved": RETRIEVED, "rehosted": False}, "sci:doi": src["doi"],
                 "sci:citation": src["attribution"]}
        item = {"type": "Feature", "stac_version": STAC_VERSION, "stac_extensions": [EXT_FILE, EXT_SCI], "id": r["id"], "geometry": None,
                "properties": props, "assets": {"data": {"href": r["href"], "type": "application/zip", "roles": ["data", "archive"], "file:size": r["size"]}},
                "links": [{"rel": "root", "href": rel(item_path, OUT / "catalog.json")}, {"rel": "parent", "href": rel(item_path, coll_path)},
                          {"rel": "collection", "href": rel(item_path, coll_path)}, {"rel": "self", "href": f"./{r['id']}.json"},
                          {"rel": "license", "href": src["license"][1]}, {"rel": "cite-as", "href": f"https://doi.org/{src['doi']}"}],
                "collection": r["source"]}
        item_dir.mkdir(parents=True, exist_ok=True)
        item_path.write_text(json.dumps(item, ensure_ascii=False, indent=1))
        items_by_coll[r["source"]].append((item, item_path))
        flat_rows.append(_flat(item, item_path))

    # ---- collections
    root_links = [{"rel": "root", "href": "./catalog.json", "type": "application/json"},
                  {"rel": "self", "href": "./catalog.json", "type": "application/json"}]
    for sid, lst in sorted(items_by_coll.items()):
        src = SOURCES[sid]
        cpath = OUT / "collections" / sid / "collection.json"
        dts = sorted(parse_dt(i["properties"]["datetime"]) for i, _ in lst)
        pts = [i["bbox"] for i, _ in lst if i.get("bbox")]
        bbox = [min(p[0] for p in pts), min(p[1] for p in pts), max(p[2] for p in pts), max(p[3] for p in pts)] if pts else [-180, -90, 180, 90]
        summ = {}
        for key in ("bim:format", "bim:format_version", "bim:building_type", "bim:country", "bim:use_cases", "bim:disciplines", "bim:license_tier"):
            vals = Counter()
            for i, _ in lst:
                v = i["properties"].get(key)
                for x in (v if isinstance(v, list) else [v]):
                    if x:
                        vals[x] += 1
            if vals:
                summ[key] = sorted(vals)
        coll = {
            "type": "Collection", "stac_version": STAC_VERSION, "stac_extensions": [EXT_SCI] if src.get("doi") else [],
            "id": sid, "title": src["title"], "description": src["description"],
            "license": src["license"][0] if " " not in src["license"][0] else "other",
            "keywords": src.get("keywords", []), "providers": src["providers"],
            "extent": {"spatial": {"bbox": [bbox]}, "temporal": {"interval": [[dts[0].isoformat().replace("+00:00", "Z"), dts[-1].isoformat().replace("+00:00", "Z")]]}},
            "summaries": summ,
            "bim:license_tier": src["tier"], "bim:license_quote": src["license_quote"], "bim:attribution": src["attribution"],
            "bim:origin": {k: v for k, v in src["origin"].items() if k != "raw_dir"}, "bim:retrieved": RETRIEVED,
            "bim:item_count": len(lst), "bim:license_cross_check": {"href": LICENSE_SURVEY[0], "title": LICENSE_SURVEY[1]},
            **({"sci:doi": src["doi"], "sci:citation": src["attribution"]} if src.get("doi") else {}),
            "links": [{"rel": "root", "href": rel(cpath, OUT / "catalog.json"), "type": "application/json"},
                      {"rel": "parent", "href": rel(cpath, OUT / "catalog.json"), "type": "application/json"},
                      {"rel": "self", "href": "./collection.json", "type": "application/json"},
                      {"rel": "license", "href": src["license"][1], "title": src["license"][0]},
                      {"rel": "about", "href": src["homepage"], "title": "Upstream dataset page"},
                      *([{"rel": "cite-as", "href": f"https://doi.org/{src['doi']}"}] if src.get("doi") else []),
                      *[{"rel": "item", "href": rel(cpath, p), "type": "application/geo+json", "title": i["properties"]["title"]} for i, p in lst]],
        }
        cpath.write_text(json.dumps(coll, ensure_ascii=False, indent=1))
        root_links.append({"rel": "child", "href": rel(OUT / "catalog.json", cpath), "type": "application/json", "title": src["title"]})

    # ---- dimension views
    all_items = [(i, p) for lst in items_by_coll.values() for i, p in lst]
    dims = {
        "format": lambda pr: [pr.get("bim:format")],
        "format-family": lambda pr: [pr.get("bim:format_family")],
        "format-version": lambda pr: [f"{pr.get('bim:format')} {pr.get('bim:format_version')}"] if pr.get("bim:format_version") else [],
        "discipline": lambda pr: pr.get("bim:disciplines", []),
        "building-type": lambda pr: [pr.get("bim:building_type")],
        "country": lambda pr: [pr.get("bim:country")],
        "use-case": lambda pr: pr.get("bim:use_cases", []),
        "license-tier": lambda pr: [pr.get("bim:license_tier")],
        "project": lambda pr: [pr.get("bim:project")],
        "size-class": lambda pr: [pr.get("bim:size_class")],
        "has-thumbnail": lambda pr: ["yes" if str(pr.get("bim:thumbnail", "")).startswith("generated") else "no"],
    }
    DIM_TITLE = {"format": "By file format", "format-family": "By format family (IFC / CAD-2D / PDF / BIM-native / ...)",
                 "format-version": "By format version (IFC schema, DWG release, Revit version, ...)", "discipline": "By discipline",
                 "building-type": "By building / asset type", "country": "By country (ISO 3166-1 alpha-2)", "use-case": "By test use case",
                 "license-tier": "By license tier (open / open-nd / unclear / restricted)", "project": "By project (multi-file sets)",
                 "size-class": "By file size class", "has-thumbnail": "By thumbnail availability"}
    vroot = OUT / "views" / "catalog.json"
    vlinks = [{"rel": "root", "href": rel(vroot, OUT / "catalog.json")}, {"rel": "parent", "href": rel(vroot, OUT / "catalog.json")},
              {"rel": "self", "href": "./catalog.json"}]
    for dim, fn in dims.items():
        groups = defaultdict(list)
        for i, p in all_items:
            for v in fn(i["properties"]):
                if v:
                    groups[str(v)].append((i, p))
        dpath = OUT / "views" / dim / "catalog.json"
        dlinks = [{"rel": "root", "href": rel(dpath, OUT / "catalog.json")}, {"rel": "parent", "href": rel(dpath, vroot)}, {"rel": "self", "href": "./catalog.json"}]
        for val, lst in sorted(groups.items()):
            vslug = itemspec.slug(val, 40)
            vpath = OUT / "views" / dim / vslug / "catalog.json"
            cat = {"type": "Catalog", "stac_version": STAC_VERSION, "id": f"{dim}--{vslug}", "title": f"{dim}: {val}",
                   "description": f"{len(lst)} items where {dim} = {val}. Items are shared with their source collections.",
                   "bim:dimension": dim, "bim:value": val, "bim:item_count": len(lst),
                   "links": [{"rel": "root", "href": rel(vpath, OUT / "catalog.json")}, {"rel": "parent", "href": rel(vpath, dpath)},
                             {"rel": "self", "href": "./catalog.json"},
                             *[{"rel": "item", "href": rel(vpath, p), "type": "application/geo+json", "title": i["properties"]["title"]} for i, p in lst]]}
            vpath.parent.mkdir(parents=True, exist_ok=True)
            vpath.write_text(json.dumps(cat, ensure_ascii=False, indent=1))
            dlinks.append({"rel": "child", "href": rel(dpath, vpath), "title": f"{val} ({len(lst)})"})
        dcat = {"type": "Catalog", "stac_version": STAC_VERSION, "id": f"view-{dim}", "title": DIM_TITLE[dim],
                "description": f"Items grouped by {dim}.", "links": dlinks}
        dpath.write_text(json.dumps(dcat, ensure_ascii=False, indent=1))
        vlinks.append({"rel": "child", "href": rel(vroot, dpath), "title": DIM_TITLE[dim]})
    vroot.write_text(json.dumps({"type": "Catalog", "stac_version": STAC_VERSION, "id": "views", "title": "Views (multi-dimensional index)",
                                 "description": "Alternative navigation: the same items grouped by format, version, discipline, building type, "
                                                "country, test use case, license tier, project and size.", "links": vlinks}, indent=1))
    root_links.append({"rel": "child", "href": "./views/catalog.json", "type": "application/json", "title": "Views (multi-dimensional index)"})
    root_links.append({"rel": "describedby", "href": "./README.md", "type": "text/markdown", "title": "Field reference and usage"})
    root_links.append({"rel": "alternate", "href": "./items.parquet", "type": "application/vnd.apache.parquet", "title": "Flat item table (DuckDB/pandas)"})
    root = {"type": "Catalog", "stac_version": STAC_VERSION, "id": CATALOG_ID, "title": "BIM test data catalog (IFC / CAD / PDF)",
            "description": "Index of openly downloadable BIM test data: IFC (IFC2X3 to IFC5 alpha), DWG/DXF (R9 to R2018), PDF drawing sets, Revit, "
                           "Japanese Jw_cad/SXF and BIM drawing-review samples. Every asset links to its upstream source; provenance, license "
                           "and attribution are recorded per collection and per item.",
            "bim:generated": NOW.isoformat().replace("+00:00", "Z"), "bim:item_count": len(all_items), "links": root_links}
    (OUT / "catalog.json").write_text(json.dumps(root, ensure_ascii=False, indent=1))

    # ---- parquet
    import pyarrow as pa
    import pyarrow.parquet as pq
    keys = sorted({k for r in flat_rows for k in r})
    cols = {}
    for k in keys:
        vals = [r.get(k) for r in flat_rows]
        kinds = {type(v) for v in vals if v is not None}
        if len(kinds) > 1 or kinds == {dict} or kinds == {list}:  # mixed types -> text column
            vals = [None if v is None else str(v) for v in vals]
        cols[k] = vals
    table = pa.table(cols)
    pq.write_table(table, OUT / "items.parquet", compression="zstd")
    print(f"wrote {len(all_items)} items, {len(items_by_coll)} collections, {len(dims)} view dimensions")
    errs = [(i["id"], i["properties"].get("bim:extract_error")) for i, _ in all_items if i["properties"].get("bim:extract_error")]
    print(f"extract errors: {len(errs)}")
    for e in errs[:20]:
        print("  ", e)


# IfcSite coordinates that are authoring-tool defaults, not real building locations (lon, lat, tolerance deg, label)
DEFAULT_SITES = [
    (-71.06, 42.36, 0.02, "Autodesk Revit default site: Boston, MA"),
    (-87.635, 41.875, 0.02, "Autodesk Revit MEP default site: Chicago, IL"),
    (5.33, 60.38, 0.02, "DDS-CAD default site: Bergen, NO"),
    (5.387, 52.155, 0.02, "Dutch RD grid origin (Amersfoort), not the building site"),
    (54.42, 24.47, 0.02, "synthetic location in buildingSMART validation test files"),
]


def _default_location(geo):
    for lon, lat, tol, label in DEFAULT_SITES:
        if abs(geo["lon"] - lon) <= tol and abs(geo["lat"] - lat) <= tol:
            return label
    return None


def _flat(item, path):
    pr = item["properties"]
    a = item["assets"].get("data", {})
    row = {"id": item["id"], "collection": item["collection"], "item_href": str(path.relative_to(OUT)),
           "data_href": a.get("href"), "data_size": a.get("file:size"), "archive_member": a.get("bim:archive_member"),
           "thumbnail_href": str((path.parent / "thumbnail.png").relative_to(OUT)) if "thumbnail" in item["assets"] else None,
           "lon": item["geometry"]["coordinates"][0] if item.get("geometry") else None,
           "lat": item["geometry"]["coordinates"][1] if item.get("geometry") else None}
    for k, v in pr.items():
        col = k.replace(":", "_")
        row[col] = json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else (str(v) if not isinstance(v, (int, float, bool)) else v)
    return row


if __name__ == "__main__":
    main()
