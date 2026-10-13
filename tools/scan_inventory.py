"""Scan given dirs (default curated/) and write inventory.csv + summary.md into the first one.

Detects format version from file headers without fully parsing:
  IFC  -> FILE_SCHEMA (IFC2X3 / IFC4 / IFC4X3_ADD2 / ...), also .ifczip/.ifcxml
  DWG  -> magic "ACxxxx" -> AutoCAD release
  DXF  -> $ACADVER
  PDF  -> page count (pymupdf)
Usage: tools/.venv/bin/python -I tools/scan_inventory.py [curated|raw ...]
"""
import csv
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = [ROOT / a for a in sys.argv[1:]] or [ROOT / "curated"]
OUT = SCAN_DIRS[0]

DWG_VERSIONS = {
    "MC0.0": "R1.0", "AC1.2": "R1.2", "AC1.40": "R1.40", "AC1.50": "R2.05",
    "AC2.10": "R2.10", "AC1001": "R2.22", "AC1002": "R2.50", "AC1003": "R2.60",
    "AC1004": "R9", "AC1006": "R10", "AC1009": "R11/R12", "AC1012": "R13",
    "AC1014": "R14", "AC1015": "R2000", "AC1018": "R2004", "AC1021": "R2007",
    "AC1024": "R2010", "AC1027": "R2013", "AC1032": "R2018",
}
FORMATS = {
    ".ifc": "IFC", ".ifczip": "IFC", ".ifcxml": "IFC", ".ifcjson": "IFC", ".ifcx": "IFC5",
    ".jww": "JWW", ".jwc": "JWW", ".sfc": "SXF", ".p21": "SXF", ".dxfb": "DXF",
    ".dwg": "DWG", ".dxf": "DXF", ".pdf": "PDF", ".rvt": "RVT", ".rfa": "RFA",
    ".rte": "RTE", ".dwf": "DWF", ".dwfx": "DWF", ".dgn": "DGN", ".pln": "PLN",
    ".bcf": "BCF", ".bcfzip": "BCF", ".ids": "IDS", ".svg": "SVG", ".e57": "E57",
    ".nwd": "NWD", ".nwc": "NWC", ".skp": "SKP", ".3dm": "3DM", ".step": "STEP",
    ".stp": "STEP", ".obj": "OBJ", ".glb": "GLTF", ".gltf": "GLTF",
    ".xlsx": "XLSX", ".xls": "XLSX", ".zip": "ZIP", ".7z": "ARCHIVE",
    ".tar": "ARCHIVE", ".gz": "ARCHIVE",
}


def ifc_schema(p: Path) -> str:
    try:
        if p.suffix.lower() == ".ifczip":
            with zipfile.ZipFile(p) as z:
                name = next((n for n in z.namelist() if n.lower().endswith(".ifc")), None)
                head = z.open(name).read(20000).decode("latin-1") if name else ""
        else:
            with open(p, "rb") as f:
                head = f.read(20000).decode("latin-1")
    except Exception as e:  # noqa: BLE001
        return f"ERR:{type(e).__name__}"
    if p.suffix.lower() == ".ifcxml":
        m = re.search(r'(IFC[0-9A-Z_]+)', head)
        return m.group(1) if m else "ifcXML?"
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", head, re.I)
    if m:
        return m.group(1).upper()
    if head.startswith("version https://git-lfs"):
        return "LFS-POINTER"
    return "?"


def dwg_version(p: Path) -> str:
    try:
        with open(p, "rb") as f:
            magic = f.read(6).decode("latin-1")
    except Exception:  # noqa: BLE001
        return "?"
    if magic.startswith("versio"):
        return "LFS-POINTER"
    return f"{magic} {DWG_VERSIONS.get(magic, DWG_VERSIONS.get(magic[:5], ''))}".strip()


def dxf_version(p: Path) -> str:
    try:
        with open(p, "rb") as f:
            head = f.read(4000)
    except Exception:  # noqa: BLE001
        return "?"
    if head.startswith(b"AutoCAD Binary DXF"):
        m = re.search(rb"AC10\d\d", head)
        return ("binary " + m.group(0).decode()) if m else "binary"
    m = re.search(rb"\$ACADVER\s*\r?\n\s*1\s*\r?\n\s*(\S+)", head)
    if m:
        v = m.group(1).decode("latin-1")
        return f"{v} {DWG_VERSIONS.get(v, '')}".strip()
    return "no-header (R12-style)"


def pdf_pages(p: Path) -> str:
    try:
        import pymupdf
        with pymupdf.open(p) as d:
            return f"{d.page_count}p"
    except Exception as e:  # noqa: BLE001
        return f"ERR:{type(e).__name__}"


def detail(fmt: str, p: Path) -> str:
    if fmt == "IFC":
        return ifc_schema(p)
    if fmt == "DWG":
        return dwg_version(p)
    if fmt == "DXF":
        return dxf_version(p)
    if fmt == "PDF":
        return pdf_pages(p)
    if fmt == "JWW":
        return magic(p, 8)
    if fmt == "SXF":
        return "SFC" if p.suffix.lower() == ".sfc" else "P21"
    if fmt == "IFC5":
        return "ifcx JSON" if magic(p, 1) == "{" else "?"
    return ""


def magic(p: Path, n: int) -> str:
    with open(p, "rb") as f:
        return f.read(n).decode("latin-1")


def main():
    OUT.mkdir(exist_ok=True)
    rows = []
    for base in SCAN_DIRS:
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for fn in filenames:
                p = Path(dirpath) / fn
                ext = p.suffix.lower()
                fmt = FORMATS.get(ext)
                if not fmt:
                    continue
                rel = p.relative_to(ROOT)
                source = rel.parts[1] if len(rel.parts) > 2 else ""
                rows.append({
                    "area": rel.parts[0], "source": source, "format": fmt,
                    "detail": detail(fmt, p), "size_bytes": p.stat().st_size,
                    "path": str(rel),
                })
    rows.sort(key=lambda r: (r["format"], r["detail"], r["path"]))
    with open(OUT / "inventory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    by_fmt = Counter(r["format"] for r in rows)
    size_fmt = Counter()
    for r in rows:
        size_fmt[r["format"]] += r["size_bytes"]
    by_ver = defaultdict(Counter)
    for r in rows:
        if r["format"] in ("IFC", "DWG", "DXF"):
            key = r["detail"] if r["format"] != "IFC" else r["detail"].split(" ")[0]
            by_ver[r["format"]][key] += 1
    by_src = defaultdict(Counter)
    for r in rows:
        by_src[r["source"]][r["format"]] += 1

    lines = ["# Inventory summary", "", f"Total indexed files: {len(rows)}", "",
             "## By format", "", "| format | files | size |", "|---|---:|---:|"]
    for k, v in by_fmt.most_common():
        lines.append(f"| {k} | {v} | {size_fmt[k] / 1e6:,.1f} MB |")
    for fmt in ("IFC", "DWG", "DXF"):
        lines += ["", f"## {fmt} versions", "", "| version | files |", "|---|---:|"]
        for k, v in sorted(by_ver[fmt].items(), key=lambda kv: -kv[1]):
            lines.append(f"| {k} | {v} |")
    lines += ["", "## By source", "", "| source | formats |", "|---|---|"]
    for src in sorted(by_src):
        lines.append(f"| {src} | " + ", ".join(f"{k}:{v}" for k, v in by_src[src].most_common()) + " |")
    (OUT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:40]))


if __name__ == "__main__":
    sys.exit(main())
