"""Score IFC files by how "data-complete" they are (semantics, not geometry).

For each IFC: element type variety, property sets, quantity sets, materials,
spaces, classifications, zones/systems, discipline coverage. Writes CSV sorted by score.
Usage: tools/.venv/bin/python -I tools/ifc_richness.py OUT.csv FILE_LIST.txt
"""
import csv
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

ARCH = {"IfcWall", "IfcWallStandardCase", "IfcSlab", "IfcDoor", "IfcWindow", "IfcRoof", "IfcStair", "IfcRailing", "IfcCurtainWall", "IfcCovering"}
STRUCT = {"IfcBeam", "IfcColumn", "IfcFooting", "IfcPile", "IfcMember", "IfcPlate", "IfcReinforcingBar", "IfcTendon"}
MEP = {"IfcFlowSegment", "IfcFlowFitting", "IfcFlowTerminal", "IfcDistributionElement", "IfcDistributionFlowElement",
       "IfcPipeSegment", "IfcDuctSegment", "IfcCableSegment", "IfcEnergyConversionDevice", "IfcFlowController",
       "IfcFlowMovingDevice", "IfcSanitaryTerminal", "IfcLightFixture", "IfcAirTerminal", "IfcOutlet"}


def analyse(path):
    import ifcopenshell
    try:
        f = ifcopenshell.open(path)
    except Exception as e:  # noqa: BLE001
        return {"path": path, "error": type(e).__name__}
    n = lambda t: len(f.by_type(t)) if _has(f, t) else 0  # noqa: E731
    products = [p for p in f.by_type("IfcProduct") if not p.is_a("IfcSpatialStructureElement") and not p.is_a("IfcOpeningElement")
                and not p.is_a("IfcAnnotation") and not p.is_a("IfcGrid")]
    types = {p.is_a() for p in products}
    present = {g for g, s in (("A", ARCH), ("S", STRUCT), ("M", MEP)) if any(n(t) for t in s)}
    psets = [p for p in f.by_type("IfcPropertySet")]
    pset_names = {p.Name for p in psets}
    props = sum(len(p.HasProperties or ()) for p in psets)
    qsets = n("IfcElementQuantity")
    r = {
        "path": path, "schema": f.schema, "products": len(products), "product_types": len(types),
        "disciplines": "".join(sorted(present)), "storeys": n("IfcBuildingStorey"), "spaces": n("IfcSpace"),
        "zones": n("IfcZone"), "systems": n("IfcSystem"), "psets": len(psets), "pset_names": len(pset_names),
        "props": props, "qsets": qsets, "materials": n("IfcMaterial"),
        "classif_refs": n("IfcClassificationReference"), "type_objects": n("IfcTypeObject"),
        "docs": n("IfcDocumentReference") + n("IfcDocumentInformation"),
    }
    # log-scaled: rewards breadth of information, not raw size
    lg = lambda v: math.log10(1 + v)  # noqa: E731
    r["score"] = round(
        3 * lg(r["product_types"]) + 2 * lg(r["pset_names"]) + 1.5 * lg(r["props"] / max(1, r["products"]))
        + 2 * (r["qsets"] > 0) + lg(r["qsets"]) + 2 * (r["spaces"] > 0) + 1.5 * (r["materials"] > 0)
        + 1.5 * (r["classif_refs"] > 0) + 1 * (r["type_objects"] > 0) + 1 * (r["systems"] + r["zones"] > 0)
        + 1.5 * len(present) + 0.5 * (r["storeys"] > 1), 2)
    return r


def _has(f, t):
    try:
        f.by_type(t)
        return True
    except RuntimeError:
        return False


def main():
    out, listfile = sys.argv[1], sys.argv[2]
    paths = [l.strip() for l in open(listfile, encoding="utf-8") if l.strip()]
    rows = []
    with ProcessPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(analyse, p): p for p in paths}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                rows.append(fut.result())
            except Exception as e:  # noqa: BLE001
                rows.append({"path": futs[fut], "error": type(e).__name__})
            print(f"[{i}/{len(paths)}] {rows[-1].get('score', 'ERR')} {futs[fut]}", flush=True)
    keys = ["score", "schema", "disciplines", "products", "product_types", "storeys", "spaces", "zones", "systems",
            "psets", "pset_names", "props", "qsets", "materials", "classif_refs", "type_objects", "docs", "path", "error"]
    rows.sort(key=lambda r: -r.get("score", -1))
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in keys})


if __name__ == "__main__":
    main()
