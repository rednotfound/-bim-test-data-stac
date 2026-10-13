"""Per-format metadata extraction for STAC items (reads local copies of upstream files)."""
import datetime as dt
import hashlib
import io
import json
import re
import subprocess
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
DWG2DXF = TOOLS / "libredwg/bin/dwg2dxf"

DWG_RELEASES = {
    "AC1004": "R9", "AC1006": "R10", "AC1009": "R11/R12", "AC1012": "R13", "AC1014": "R14", "AC1015": "R2000",
    "AC1018": "R2004", "AC1021": "R2007", "AC1024": "R2010", "AC1027": "R2013", "AC1032": "R2018",
}
INSUNITS = {0: "unitless", 1: "inch", 2: "foot", 4: "millimeter", 5: "centimeter", 6: "meter"}
PAPER = {  # (short, long) in mm, tolerance 3 mm
    "A0": (841, 1189), "A1": (594, 841), "A2": (420, 594), "A3": (297, 420), "A4": (210, 297),
    "B1(JIS)": (728, 1030), "B2(JIS)": (515, 728), "B3(JIS)": (364, 515), "B4(JIS)": (257, 364),
    "ARCH D": (610, 914), "ARCH E": (914, 1219), "ANSI D": (559, 864), "ANSI B": (279, 432), "Letter": (216, 279),
}


def file_info(p: Path) -> dict:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return {"file:size": p.stat().st_size, "file:checksum": "1220" + h.hexdigest()}


def _ts(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s[:19], fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- IFC (STEP)
def _step_header(text: str) -> dict:
    out = {}
    m = re.search(r"FILE_DESCRIPTION\s*\(\s*\((.*?)\)\s*,", text, re.S)
    if m:
        desc = re.findall(r"'((?:[^']|'')*)'", m.group(1))
        out["ifc:file_description"] = [d for d in desc if d][:6]
        vd = [d for d in desc if "ViewDefinition" in d]
        if vd:
            out["ifc:view_definition"] = re.sub(r"ViewDefinition\s*\[|\]", "", vd[0]).strip(" ,")
    m = re.search(r"FILE_NAME\s*\((.*?)\)\s*;", text, re.S)
    if m:
        vals = re.findall(r"'((?:[^']|'')*)'", m.group(1))
        if len(vals) >= 2:
            out["ifc:header_timestamp"] = vals[1]
        tail = [v for v in vals[2:] if v]
        if tail:
            out["ifc:preprocessor_version"] = tail[-2] if len(tail) >= 2 else tail[-1]
            out["ifc:originating_system"] = tail[-1] if len(tail) >= 2 else None
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", text, re.I)
    if m:
        out["ifc:schema"] = m.group(1).upper()
    return {k: v for k, v in out.items() if v}


def ifc_meta(p: Path) -> dict:
    with open(p, "rb") as f:
        head = f.read(30000).decode("latin-1")
    meta = _step_header(head)
    meta["bim:format"] = "IFC-SPF"
    try:
        import ifcopenshell
        import ifcopenshell.util.unit as uu
        f = ifcopenshell.open(str(p))
    except Exception as e:  # noqa: BLE001
        meta["ifc:parse_error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return meta
    sys.path.insert(0, str(TOOLS))
    from ifc_richness import analyse  # reuse scoring
    r = analyse(str(p))
    for k in ("products", "product_types", "storeys", "spaces", "zones", "systems", "pset_names", "props", "qsets",
              "materials", "classif_refs", "type_objects", "docs", "score"):
        if k in r:
            meta[f"ifc:{k}"] = r[k]
    try:
        fn, fd = f.header.file_name, f.header.file_description
        meta["ifc:preprocessor_version"] = fn.preprocessor_version or None
        meta["ifc:originating_system"] = fn.originating_system or None
        meta["ifc:header_timestamp"] = fn.time_stamp or None
        desc = [d for d in fd.description if d]
        meta["ifc:file_description"] = desc[:8]
        vd = [d for d in desc if "ViewDefinition" in d]
        meta["ifc:view_definition"] = re.sub(r"ViewDefinition\s*\[|\]", "", vd[0]).strip(" ,") if vd else None
    except Exception:  # noqa: BLE001
        pass
    meta["ifc:disciplines"] = sorted({"A": "architecture", "S": "structure", "M": "mep"}[c] for c in r.get("disciplines", ""))
    prods = [e for e in f.by_type("IfcProduct") if not e.is_a("IfcSpatialStructureElement") and not e.is_a("IfcOpeningElement")]
    meta["ifc:element_counts"] = dict(Counter(e.is_a() for e in prods).most_common(25))
    try:
        meta["ifc:entity_instances"] = len(f)
    except TypeError:
        pass
    meta["ifc:pset_names"] = sorted({ps.Name for ps in f.by_type("IfcPropertySet") if ps.Name})[:60]
    classif = sorted({c.Name for c in f.by_type("IfcClassification") if c.Name})
    if classif:
        meta["ifc:classification_systems"] = classif
    proj = f.by_type("IfcProject")
    if proj:
        meta["ifc:project_name"] = proj[0].Name or proj[0].LongName
        try:
            meta["ifc:length_unit"] = uu.get_full_unit_name(uu.get_project_unit(f, "LENGTHUNIT"))
        except Exception:  # noqa: BLE001
            pass
    bld = f.by_type("IfcBuilding")
    if bld:
        meta["ifc:building_names"] = [b.Name for b in bld if b.Name][:5]
    meta["ifc:storey_names"] = [s.Name for s in f.by_type("IfcBuildingStorey") if s.Name][:30]
    try:
        meta["ifc:map_conversion"] = bool(f.by_type("IfcMapConversion"))
    except RuntimeError:
        meta["ifc:map_conversion"] = False
    geo = _ifc_site_location(f)
    if geo:
        meta["_geometry"] = geo
    return {k: v for k, v in meta.items() if v not in (None, [], {})}


def _dms(v):
    if not v:
        return None
    v = list(v) + [0] * (4 - len(v))
    sign = -1 if any(x < 0 for x in v[:3]) else 1
    return sign * (abs(v[0]) + abs(v[1]) / 60 + abs(v[2]) / 3600 + abs(v[3]) / 3.6e9)


def _ifc_site_location(f):
    for s in f.by_type("IfcSite"):
        lat, lon = _dms(s.RefLatitude), _dms(s.RefLongitude)
        if lat is None or lon is None:
            continue
        if abs(lat) < 1e-6 and abs(lon) < 1e-6:
            return {"status": "zero"}
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return {"status": "invalid"}
        return {"status": "ok", "lat": round(lat, 6), "lon": round(lon, 6), "elevation": s.RefElevation}
    return None


# ---------------------------------------------------------------- DWG / DXF / JWW
def _dxf_doc_meta(doc) -> dict:
    msp = doc.modelspace()
    counts = Counter(e.dxftype() for e in msp)
    hdr = doc.header
    meta = {
        "cad:layers": len(doc.layers), "cad:blocks": len([b for b in doc.blocks if not b.name.startswith("*")]),
        "cad:layouts": len(doc.layouts) - 1, "cad:modelspace_entities": sum(counts.values()),
        "cad:entity_counts": dict(counts.most_common(20)),
        "cad:units": INSUNITS.get(hdr.get("$INSUNITS", 0), str(hdr.get("$INSUNITS"))),
        "cad:text_styles": len(doc.styles),
    }
    try:
        ext = (hdr.get("$EXTMIN"), hdr.get("$EXTMAX"))
        if ext[0] and ext[1] and abs(ext[1][0]) < 1e19:
            meta["cad:extents"] = [round(ext[0][0], 3), round(ext[0][1], 3), round(ext[1][0], 3), round(ext[1][1], 3)]
    except Exception:  # noqa: BLE001
        pass
    names = [l.dxf.name for l in doc.layers][:80]
    meta["cad:layer_names"] = names
    if any(re.search(r"[぀-ヿ一-鿿]", n) for n in names):
        meta["cad:has_cjk_layer_names"] = True
    return meta


def dxf_meta(p: Path, keep_doc=False):
    import ezdxf
    from ezdxf import recover
    with open(p, "rb") as f:
        head = f.read(4000)
    meta = {"bim:format": "DXF"}
    if head.startswith(b"AutoCAD Binary DXF"):
        meta["cad:dxf_encoding"] = "binary"
    m = re.search(rb"\$ACADVER\s*\r?\n\s*1\s*\r?\n\s*(\S+)", head)
    if m:
        v = m.group(1).decode()
        meta["cad:version_code"], meta["cad:release"] = v, DWG_RELEASES.get(v)
    try:
        doc, auditor = recover.readfile(str(p))
        meta.update(_dxf_doc_meta(doc))
        meta["cad:audit_errors"] = len(auditor.errors)
        if "cad:version_code" not in meta:  # file header ($ACADVER) wins; ezdxf upgrades R13/R14 to AC1015 internally
            meta["cad:version_code"] = doc.dxfversion
            meta["cad:release"] = DWG_RELEASES.get(doc.dxfversion)
        elif doc.dxfversion != meta["cad:version_code"]:
            meta["cad:loaded_as"] = doc.dxfversion
    except Exception as e:  # noqa: BLE001
        meta["cad:parse_error"] = f"{type(e).__name__}: {str(e)[:120]}"
        doc = None
    return (meta, doc) if keep_doc else meta


def dwg_meta(p: Path, keep_doc=False):
    with open(p, "rb") as f:
        magic = f.read(6).decode("latin-1")
    meta = {"bim:format": "DWG", "cad:version_code": magic, "cad:release": DWG_RELEASES.get(magic)}
    doc = None
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "x.dxf"
        try:
            subprocess.run([str(DWG2DXF), "-y", "-o", str(out), str(p)], capture_output=True, timeout=240)
        except subprocess.TimeoutExpired:
            pass
        if out.exists() and out.stat().st_size > 0:
            m, doc = dxf_meta(out, keep_doc=True)
            for k in ("cad:version_code", "cad:release", "bim:format", "cad:dxf_encoding"):
                m.pop(k, None)
            meta.update(m)
            meta["cad:read_via"] = "LibreDWG 0.14 dwg2dxf"
        else:
            meta["cad:parse_error"] = "LibreDWG dwg2dxf failed"
    meta = {k: v for k, v in meta.items() if v is not None}
    return (meta, doc) if keep_doc else meta


def jww_meta(p: Path, keep_doc=False):
    import ezjww
    with open(p, "rb") as f:
        head = f.read(12)
    meta = {"bim:format": "JWW", "cad:version_code": int.from_bytes(head[8:12], "little") if head.startswith(b"JwwData.") else None}
    doc = None
    try:
        d = ezjww.readfile(str(p))
        st = d.stats() if callable(getattr(d, "stats", None)) else None
        if st:
            meta["cad:jww_stats"] = json.loads(json.dumps(st, default=str))
        import ezdxf
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "x.dxf"
            d.save_dxf(str(out))
            doc = ezdxf.readfile(str(out))
        m = _dxf_doc_meta(doc)
        meta.update({k: v for k, v in m.items() if k != "cad:units"})
        meta["cad:units"] = "millimeter (paper)"
        meta["cad:read_via"] = "ezjww"
    except Exception as e:  # noqa: BLE001
        meta["cad:parse_error"] = f"{type(e).__name__}: {str(e)[:120]}"
    meta = {k: v for k, v in meta.items() if v is not None}
    return (meta, doc) if keep_doc else meta


def sfc_meta(p: Path) -> dict:
    raw = p.read_bytes()
    text = raw.decode("cp932", errors="replace")
    feats = Counter(re.findall(r"/\*SXF\s*\n?#\d+\s*=\s*([a-z_]+)\(", text) or re.findall(r"=\s*([a-z_]+_feature)\(", text))
    meta = {"bim:format": "SXF", "cad:sxf_flavour": "SFC", "cad:entity_counts": dict(feats.most_common(20)),
            "cad:modelspace_entities": sum(feats.values())}
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", text)
    if m:
        meta["cad:sxf_schema"] = m.group(1)
    layers = re.findall(r"layer_feature\('([^']*)'", text)
    if layers:
        meta["cad:layers"] = len(layers)
        meta["cad:layer_names"] = layers[:80]
    sheet = re.search(r"sheet_feature\('[^']*','([^']*)','(\d+)'", text)
    if sheet:
        meta["cad:sheet"] = {"name": sheet.group(1), "size_code": sheet.group(2)}
    return meta


# ---------------------------------------------------------------- PDF
def pdf_meta(p: Path) -> dict:
    import pymupdf
    meta = {"bim:format": "PDF"}
    with pymupdf.open(p) as d:
        meta["pdf:pages"] = d.page_count
        md = d.metadata or {}
        for k in ("title", "creator", "producer"):
            if md.get(k):
                meta[f"pdf:{k}"] = md[k]
        meta["pdf:version"] = md.get("format")
        created = md.get("creationDate", "")
        m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?", created)
        if m:
            meta["_datetime"] = dt.datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4] or 0), int(m[5] or 0), tzinfo=dt.timezone.utc)
        sizes = Counter()
        vec = img = text_pages = 0
        cjk = False
        for i, page in enumerate(d):
            w, h = page.rect.width * 25.4 / 72, page.rect.height * 25.4 / 72
            sizes[_paper_name(w, h)] += 1
            if i < 30:
                vec += len(page.get_drawings()) > 50
                img += len(page.get_images()) > 0
                t = page.get_text()
                text_pages += len(t.strip()) > 20
                cjk = cjk or bool(re.search(r"[぀-ヿ一-鿿]", t))
        meta["pdf:page_sizes"] = dict(sizes.most_common())
        n = min(30, d.page_count)
        meta["pdf:vector_pages_ratio"] = round(vec / n, 2) if n else 0
        meta["pdf:raster_pages_ratio"] = round(img / n, 2) if n else 0
        meta["pdf:text_extractable"] = text_pages > 0
        meta["pdf:language_cjk"] = cjk
    return {k: v for k, v in meta.items() if v is not None}


def _paper_name(w, h):
    s, l = sorted((w, h))
    for name, (a, b) in PAPER.items():
        if abs(s - a) < 4 and abs(l - b) < 4:
            return f"{name} {'landscape' if w > h else 'portrait'}"
    return f"{round(w)}x{round(h)}mm"


# ---------------------------------------------------------------- other formats
def ifcx_meta(p: Path) -> dict:
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    hdr = d.get("header", {})
    data = d.get("data", [])
    meta = {"bim:format": "IFCX", "ifc:schema": "IFC5-alpha", "ifcx:header": {k: v for k, v in hdr.items() if isinstance(v, (str, int, float))},
            "ifcx:nodes": len(data), "ifcx:imports": [i.get("uri") for i in d.get("imports", []) if isinstance(i, dict)][:20]}
    attrs = Counter()
    for node in data:
        for k in (node.get("attributes") or {}):
            attrs[k] += 1
    meta["ifcx:attribute_counts"] = dict(attrs.most_common(25))
    return meta


def ids_meta(p: Path) -> dict:
    import xml.etree.ElementTree as ET
    root = ET.parse(p).getroot()
    ns = {"ids": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
    q = (lambda t: f"ids:{t}") if ns else (lambda t: t)
    info = root.find(q("info"), ns)
    specs = root.findall(f".//{q('specification')}", ns)
    meta = {"bim:format": "IDS", "ids:namespace": ns.get("ids"), "ids:specifications": len(specs),
            "ids:ifc_versions": sorted({s.get("ifcVersion") for s in specs if s.get("ifcVersion")})}
    if info is not None:
        for t in ("title", "version", "author", "date", "purpose"):
            e = info.find(q(t), ns)
            if e is not None and e.text:
                meta[f"ids:{t}"] = e.text.strip()
    return meta


def bcf_meta(p: Path) -> dict:
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        ver = None
        if "bcf.version" in names:
            m = re.search(rb'VersionId="([^"]+)"', z.read("bcf.version"))
            ver = m.group(1).decode() if m else None
        topics = {n.split("/")[0] for n in names if n.endswith("markup.bcf")}
        return {"bim:format": "BCF", "bcf:version": ver, "bcf:topics": len(topics),
                "bcf:viewpoints": sum(n.endswith(".bcfv") for n in names), "bcf:snapshots": sum(n.endswith(".png") for n in names)}


def rvt_meta(p: Path) -> dict:
    import olefile
    meta = {"bim:format": "RVT"}
    try:
        with olefile.OleFileIO(str(p)) as ole:
            if ole.exists("BasicFileInfo"):
                raw = ole.openstream("BasicFileInfo").read()
                txt = raw.decode("utf-16-le", errors="ignore")
                m = re.search(r"Format:\s*(\d{4})", txt) or re.search(r"Autodesk Revit (\d{4})", txt)
                b = re.search(r"Build:\s*(\d{8}_\d{4}(?:\(x64\))?)", txt) or re.search(r"(\d{8}_\d{4}\(x64\))", txt)
                if b:
                    meta["rvt:build"] = b.group(1)
                if m:
                    meta["rvt:revit_version"] = m.group(1)
                elif b:  # Revit releases ship in spring with next year's name; builds are dated YYYYMMDD
                    y, mo = int(b.group(1)[:4]), int(b.group(1)[4:6])
                    meta["rvt:revit_version"] = str(y + 1 if mo >= 3 else y)
                    meta["rvt:revit_version_estimated_from_build"] = True
                w = re.search(r"Worksharing:\s*([A-Za-z ]+?)\s*(?:\n|Username)", txt)
                if w:
                    meta["rvt:worksharing"] = w.group(1).strip()
    except Exception as e:  # noqa: BLE001
        meta["rvt:parse_error"] = f"{type(e).__name__}"
    return meta


def xlsx_meta(p: Path) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(p, read_only=True)
    sheets = wb.sheetnames
    meta = {"bim:format": "XLSX", "xlsx:sheets": sheets}
    if {"Facility", "Floor", "Space", "Component"} <= set(sheets):
        meta["xlsx:cobie"] = True
    return meta


def zip_listing(p: Path) -> dict:
    with zipfile.ZipFile(p) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        ext = Counter(Path(i.filename).suffix.lower() for i in infos)
        dwg_versions = Counter()
        for i in infos:
            if i.filename.lower().endswith(".dwg"):
                dwg_versions[z.open(i).read(6).decode("latin-1")] += 1
    meta = {"archive:files": len(infos), "archive:extensions": dict(ext.most_common()),
            "archive:uncompressed_size": sum(i.file_size for i in infos)}
    if dwg_versions:
        meta["cad:dwg_versions"] = {f"{k} {DWG_RELEASES.get(k, '')}".strip(): v for k, v in dwg_versions.items()}
    return meta


import sys  # noqa: E402  (used by ifc_meta)

EXTRACTORS = {".ifc": ifc_meta, ".dwg": dwg_meta, ".dxf": dxf_meta, ".dxfb": dxf_meta, ".jww": jww_meta, ".sfc": sfc_meta,
              ".pdf": pdf_meta, ".ifcx": ifcx_meta, ".ids": ids_meta, ".bcf": bcf_meta, ".bcfzip": bcf_meta,
              ".rvt": rvt_meta, ".xlsx": xlsx_meta}


def extract(p: Path) -> dict:
    ext = p.suffix.lower()
    if ext in (".ifcxml",):
        return {"bim:format": "IFC-XML", "ifc:schema": _ifcxml_schema(p)}
    if ext == ".ifczip":
        with zipfile.ZipFile(p) as z:
            inner = z.namelist()[0]
            head = z.open(inner).read(30000).decode("latin-1")
        m = _step_header(head) if not inner.lower().endswith("xml") else {"ifc:schema": _ifcxml_schema_text(head)}
        return {"bim:format": "IFC-ZIP", "ifc:zip_member": inner, **m}
    fn = EXTRACTORS.get(ext)
    return fn(p) if fn else {}


def _ifcxml_schema(p):
    return _ifcxml_schema_text(p.read_bytes()[:20000].decode("utf-8", "ignore"))


def _ifcxml_schema_text(t):
    m = re.search(r"(IFC[0-9A-Z_]+)", t)
    return m.group(1) if m else None
