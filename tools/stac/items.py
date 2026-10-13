"""Which upstream files become STAC items, where they link to, and their classification tags.

Every spec: id, source, title, project, tags{building_type, country, use_cases, disciplines}, assets[{key, local, href,
media_type, roles, archive_member?}]. The first asset with role "data" drives metadata extraction.
"""
import hashlib
import re
import subprocess
import urllib.parse
from pathlib import Path

from sources import SOURCES

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "raw"
CUR = ROOT / "curated"

MEDIA = {
    ".ifc": "application/x-step", ".ifczip": "application/zip", ".ifcxml": "application/xml", ".ifcx": "application/json",
    ".dwg": "image/vnd.dwg", ".dxf": "image/vnd.dxf", ".dxfb": "image/vnd.dxf", ".pdf": "application/pdf",
    ".rvt": "application/octet-stream", ".jww": "application/octet-stream", ".sfc": "text/plain",
    ".ids": "application/xml", ".bcf": "application/zip", ".bcfzip": "application/zip",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".zip": "application/zip",
}

_LFS_CACHE = {}


def _is_lfs(repo_dir: Path, rel: str) -> bool:
    """True if the blob committed at HEAD is a Git LFS pointer (independent of .gitattributes case rules)."""
    if repo_dir not in _LFS_CACHE:
        out = subprocess.run(["git", "-C", str(repo_dir), "lfs", "ls-files", "--name-only"], capture_output=True, text=True,
                             env={"PATH": f"{ROOT / 'tools/bin'}:/usr/bin:/bin"}).stdout
        _LFS_CACHE[repo_dir] = set(out.splitlines())
    return rel in _LFS_CACHE[repo_dir]


def git_href(source_id: str, rel: str, repo=None, commit=None, raw_dir=None) -> str:
    o = SOURCES[source_id]["origin"]
    repo, commit, raw_dir = repo or o["repo"], commit or o["commit"], raw_dir or o["raw_dir"]
    q = urllib.parse.quote(rel)
    if _is_lfs(RAW / raw_dir, rel):
        return f"https://media.githubusercontent.com/media/{repo}/{commit}/{q}"
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{q}"


def slug(text: str, n=60) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    h = hashlib.sha1(text.encode()).hexdigest()[:6]
    return (s[:n].strip("-") + "-" + h) if s else h


SPECS = []


def add(source, local, href, title=None, project=None, archive_member=None, extra_assets=(), **tags):
    local = Path(local)
    ext = local.suffix.lower()
    h = hashlib.sha1(str(local.relative_to(ROOT)).encode()).hexdigest()[:6]
    stem = re.sub(r"[^A-Za-z0-9]+", "-", local.stem).strip("-").lower()[:50].strip("-")
    spec_id = f"{source}.{stem + '-' if stem else ''}{h}"
    data = {"key": "data", "local": local, "href": href, "media_type": MEDIA.get(ext, "application/octet-stream"),
            "roles": ["data"], "title": local.name}
    if archive_member:
        data.update(media_type="application/zip", roles=["data", "archive"], archive_member=archive_member,
                    member_media_type=MEDIA.get(ext, "application/octet-stream"))
    SPECS.append({"id": spec_id, "source": source, "title": title or local.stem, "project": project,
                  "assets": [data, *extra_assets], "tags": tags})


def g(source, rel, **kw):
    """Item from a git source: local path under raw/<raw_dir>/<rel>, href pinned to commit."""
    o = SOURCES[source]["origin"]
    rel = SOURCES[source].get("path_prefix", "") + rel
    add(source, RAW / o["raw_dir"] / rel, git_href(source, rel), **kw)


# ----------------------------------------------------------------------------- tag helpers
def scene_tags(name):
    bt = {"Infra-Road": "road", "Infra-Bridge": "bridge", "Infra-Rail": "railway", "Infra-Plumbing": "utility-network",
          "Infra-Electrical": "utility-network", "Infra-Landscaping": "landscape", "Building-Landscaping": "landscape"}.get(name, "generic-building")
    disc = {"Building-Architecture": ["architecture"], "Building-Structural": ["structure"], "Building-Hvac": ["mep"],
            "Infra-Plumbing": ["mep", "infrastructure"], "Infra-Electrical": ["mep", "infrastructure"]}.get(name, ["infrastructure"] if name.startswith("Infra") else ["site"])
    return dict(building_type=bt, disciplines=disc)


SCENE = ["Building-Architecture", "Building-Structural", "Building-Hvac", "Building-Landscaping", "Infra-Road",
         "Infra-Bridge", "Infra-Rail", "Infra-Plumbing", "Infra-Electrical", "Infra-Landscaping"]

# ----------------------------------------------------------------------------- 1. same scene across schema versions
for folder, ver in [("IFC 2.3.0.1 (IFC 2x3 TC1)", "IFC2X3"), ("IFC 4.0.2.1 (IFC 4 ADD2 TC1)", "IFC4"), ("IFC 4.3.2.0 (IFC 4.3 ADD2)", "IFC4X3_ADD2")]:
    for s in SCENE:
        g("bsi-certification-datasets", f"{folder}/Simple-Scene/{s}.ifc", title=f"Simple-Scene {s} ({ver})",
          project="bsi-simple-scene", use_cases=["schema-versions", "parser", "certification"], **scene_tags(s))
for p in sorted((RAW / "bsi_Sample-Test-Files/IFC 4.0.2.1 (IFC 4 ADD2 TC1)/ISO Spec - ReferenceView_V1.2").glob("*.ifc")):
    g("bsi-certification-datasets", str(p.relative_to(RAW / "bsi_Sample-Test-Files")), title=f"ISO ReferenceView example: {p.stem}",
      use_cases=["geometry", "parser"], building_type="component", disciplines=["architecture"])
for s in SCENE:
    g("bsi-ifc5-development", f"examples/PCERT-Sample-Scene/{s}.ifcx", title=f"Simple-Scene {s} (IFC5 alpha)",
      project="bsi-simple-scene", use_cases=["schema-versions", "future-standards"], **scene_tags(s))
for f, t in [("IFC Hero Model.ifc", "IFC Hero Model (IFC4 twin)"), ("IFC Hero Model.ifcx", "IFC Hero Model (IFC5 alpha)")]:
    g("bsi-ifc5-development", f"examples/IFC Hero Model/{f}", title=t, project="ifc5-hero-model",
      use_cases=["schema-versions", "future-standards"], building_type="generic-building", disciplines=["architecture"])

# ----------------------------------------------------------------------------- 2. classic buildings
KIT = SOURCES["kit-ifc-examples"]["origin"]["base"]
for f, t, bt in [("AC20-FZK-Haus.ifc", "KIT FZK-Haus (IFC4)", "residential"), ("AC20-Institute-Var-2.ifc", "KIT Institute Var-2 office (IFC4)", "office"),
                 ("KIT-Simple-Road-Test-Web-IFC4x3_RC2.ifc", "KIT Simple Road (IFC4x3 RC2)", "road")]:
    add("kit-ifc-examples", RAW / "steptools_ifc" / f, KIT + f, title=t, country="DE", building_type=bt,
        use_cases=["parser", "reference-model"] + (["legacy-schema"] if "RC2" in f else []))
g("opensourcebim-testfiles", "TestData/data/Allplan-Smiley-West.ifc", title="KIT Smiley West (IFC2X_FINAL, Allplan)", country="DE",
  building_type="residential", use_cases=["legacy-schema"])
g("opensourcebim-testfiles", "TestData/data/HITOS_070308.ifc", title="HITOS Tromsø university college (IFC2X3)", country="NO",
  building_type="education", use_cases=["performance", "real-project"])

DUP = "IFC 2.3.0.1 (IFC 2x3)/Duplex Apartment"
for f, d in [("Duplex_A_20110907.ifc", "architecture"), ("Duplex_M_20111024_ROOMS_AND_SPACES.ifc", "mep"), ("Duplex_MEP_20110907.ifc", "mep"),
             ("Duplex_Plumbing_20121113.ifc", "mep"), ("Duplex_Electrical_20121207.ifc", "mep")]:
    g("bsi-community-sample-files", f"{DUP}/{f}", title=f"NIBS Duplex Apartment – {f[7:-4]}", project="nibs-duplex", country="US",
      building_type="residential", disciplines=[d], use_cases=["multi-discipline", "cobie", "reference-model"])
for f in ["2012-03-23-Duplex-Design.xlsx", "2012-03-23-Duplex-Handover.xlsx"]:
    g("bsi-community-sample-files", f"{DUP}/{f}", title=f"NIBS Duplex COBie – {f[17:-5]}", project="nibs-duplex", country="US",
      building_type="residential", use_cases=["cobie"])
CLI = "IFC 2.3.0.1 (IFC 2x3)/Medical-Dental Clinic"
for f, d in [("Clinic_Architectural.ifc", "architecture"), ("Clinic_Structural.ifc", "structure"), ("Clinic_HVAC.ifc", "mep"),
             ("Clinic_Plumbing.ifc", "mep"), ("Clinic_Electrical.ifc", "mep")]:
    g("bsi-community-sample-files", f"{CLI}/{f}", title=f"NIBS Medical-Dental Clinic – {f[7:-4]}", project="nibs-clinic", country="US",
      building_type="healthcare", disciplines=[d], use_cases=["multi-discipline", "cobie", "real-project"])
for f in ["2013-10-09-Clinic-Design-v14-WORKING-01.xlsx", "2013-10-09-Clinic-Handover-v14.xlsx"]:
    g("bsi-community-sample-files", f"{CLI}/{f}", title=f"NIBS Clinic COBie – {f[18:-5]}", project="nibs-clinic", country="US",
      building_type="healthcare", use_cases=["cobie"])

SCH = dict(project="schependomlaan", country="NL", building_type="residential")
g("schependomlaan", "Design model IFC/IFC Schependomlaan.ifc", title="Schependomlaan design model (Archicad, IFC2X3)",
  use_cases=["real-project", "data-rich"], disciplines=["architecture", "structure"], **SCH)
g("schependomlaan", "Design model IFC/ROOT-Compleet interne modelkwaliteit.bcfzip", title="Schependomlaan model-quality issues (BCF)",
  use_cases=["bcf", "real-project"], **SCH)
SCHD = RAW / "bsi_Community-Sample-Test-Files" / SOURCES["schependomlaan"]["path_prefix"]
for p in sorted((SCHD / "As Planned models").glob("Week*.ifc")):
    g("schependomlaan", str(p.relative_to(SCHD)), title=f"Schependomlaan as-planned 4D – {p.stem[:18]}",
      use_cases=["4d-construction", "real-project"], **SCH)
SUB = "Coordination model and subcontractors models/BIMsight Projectdata1"
for p in sorted((SCHD / SUB).iterdir()):
    if p.suffix.lower() in (".dwg", ".ifc", ".ifczip"):
        g("schependomlaan", f"{SUB}/{p.name}", title=f"Schependomlaan subcontractor – {p.stem}",
          use_cases=["federated-models", "real-project"], **SCH)
g("schependomlaan", "Planning/PDF/Schependomlaan Nijmegen 18-02-2015.pdf", title="Schependomlaan construction planning (PDF)",
  use_cases=["4d-construction"], **SCH)

# ----------------------------------------------------------------------------- 3. data-rich / real projects
WIT = "tests/ifcfiles/public"
for f, t, c, bt, uc in [
    ("ISSUE_068_ARK_NUS_skolebygg.ifc", "Norwegian school building, architecture (IFC2X3)", "NO", "education", ["data-rich", "real-project"]),
    ("ISSUE_159_kleine_Wohnung_R22.ifc", "Small apartment (Archicad, IFC4)", None, "residential", ["data-rich"]),
    ("Viadotto Acerno.ifc", "Viadotto Acerno bridge (IFC4X3_ADD2)", "IT", "bridge", ["infrastructure", "performance"]),
]:
    g("web-ifc-tests", f"{WIT}/{f}", title=t, country=c, building_type=bt, use_cases=uc)
for f, t in [("Ifc4_Revit_ARC.ifc", "Revit sample project – architecture (IFC4)"), ("Ifc4_Revit_MEP.ifc", "Revit sample project – MEP (IFC4)")]:
    g("yousheng-ifcsamplefiles", f, title=t, project="yousheng-revit-ifc4", building_type="office", use_cases=["data-rich", "multi-discipline"])
AUCK = SOURCES["auckland-openifc"]["origin"]["base"]
for f, t, c, bt, uc in [
    ("20160125Trapelo_Design_Intent.ifc", "Trapelo office, design intent (IFC4)", "US", "office", ["data-rich", "classification"]),
    ("20160125Trapelo - Existing-Trapelo_Design_Intent.ifc", "Trapelo office, design intent (IFC2X3)", "US", "office", ["data-rich", "schema-versions"]),
    ("20160125OTC-Conference Center - IFC4.ifc", "OTC Conference Center (IFC4)", "US", "conference", ["data-rich", "performance"]),
    ("20160124OTC-Conference Center.ifc", "OTC Conference Center (IFC2X3)", "US", "conference", ["data-rich", "schema-versions"]),
    ("20210215IFC4_RV_Convenience_store_Renga_4.5.ifc", "Convenience store (Renga, IFC4 Reference View)", "RU", "retail", ["data-rich"]),
    ("20160613office_model_CV2b_fordesign.ifc", "Office model CV2 for design (IFC2X3)", None, "office", ["data-rich"]),
]:
    add("auckland-openifc", RAW / "auckland_openifc" / f, AUCK + urllib.parse.quote(f), title=t, country=c, building_type=bt, use_cases=uc)
for f in sorted((RAW / "BIMvoice_ifcsamples/IFC4x3/Klassiqua-Office-Archetypes").glob("*.ifc")):
    g("klassiqua-office-archetypes", str(f.relative_to(RAW / "BIMvoice_ifcsamples")), title=f"Klassiqua office archetype {f.stem[-4:]} (IFC4X3_ADD2)",
      project="klassiqua", country="DE", building_type="office", use_cases=["schema-versions", "archetype"])
for f in sorted((RAW / "bim-whale-ifc-samples").glob("*/IFC/*.ifc")):
    g("bim-whale-samples", str(f.relative_to(RAW / "bim-whale-ifc-samples")), title=f"BIM Whale – {f.stem} (IFC2X3)",
      building_type="generic-building", use_cases=["dummy-data"] + (["performance"] if f.stat().st_size > 40e6 else []))
TUW = SOURCES["tuwien-escape-routes"]["origin"]["base"]
for f in sorted((RAW / "tuwien_escape_routes").glob("*.ifc")):
    add("tuwien-escape-routes", f, TUW + urllib.parse.quote(f.name) + "/content", title=f"Escape route model – {f.stem}",
        project="tuwien-escape-routes", country="AT", building_type="education", use_cases=["schema-versions", "safety"])

DUR_PROJ = {  # zip -> (project title, country, building type)
    "NBU_MedicalClinic_ifc": ("NIBS Medical Clinic (DURAARK)", "US", "healthcare"), "LTU_A-House_2014-09-25_ifc": ("LTU A-House", "SE", "residential"),
    "FOJAB_Landsarkivet_IFC": ("FOJAB Landsarkivet archive building", "SE", "public"), "Autodesk_210-King_ifc": ("Autodesk Research 210 King St", "CA", "office"),
    "SGD_Duplex_ifc": ("Statsbygg Duplex", "NO", "residential"), "SGD_HiTOS_ifc": ("Statsbygg HiTOS", "NO", "education"),
    "SGD_BARD_ifc": ("Statsbygg BARD", "NO", "public"), "SGD_BODO_ifc": ("Statsbygg Bodø", "NO", "public"),
    "SGD_Munkerud_ifc": ("Selvaag Munkerud house", "NO", "residential"), "SGD_Blueberry_ifc": ("Statsbygg Blueberry", "NO", "residential"),
    "NBU_Duplex_ifc": ("NIBS Duplex (DURAARK)", "US", "residential"), "KIT_Institute_ifc": ("KIT Institute", "DE", "office"),
    "KIT_Smiley-West_ifc": ("KIT Smiley West", "DE", "residential"), "NBS_Lakeside_ifc": ("NBS Lakeside (multi-vendor exports)", "GB", "hospitality"),
    "Academic_Autodesk_ifc": ("Autodesk academic sample projects", "US", "office"),
}
DUR_ZIP_URL = {z.stem: f"https://tib.eu/data/duraark/BuildingData/{'03_IFC_E57' if z.stem in ('LTU_A-House_2014-09-25_ifc', 'FOJAB_Landsarkivet_IFC', 'Autodesk_210-King_ifc') else '01_IFC'}/{z.name}"
               for z in (RAW / "duraark").glob("*.zip")}
for zdir in sorted((RAW / "duraark/_extracted").iterdir()):
    title, c, bt = DUR_PROJ[zdir.name]
    for f in sorted(zdir.rglob("*.ifc")):
        member = str(f.relative_to(zdir))
        disc = [d for k, d in (("arch", "architecture"), ("str", "structure"), ("hvac", "mep"), ("vent", "mep"), ("plumb", "mep"),
                               ("ele", "mep"), ("san", "mep"), ("mep", "mep")) if k in f.stem.lower()]
        add("duraark", f, DUR_ZIP_URL[zdir.name], title=f"{title} – {f.stem}", project=f"duraark-{slug(zdir.name, 30)}",
            archive_member=member, country=c, building_type=bt, disciplines=sorted(set(disc)) or None,
            use_cases=["real-project", "multi-vendor" if "Lakeside" in zdir.name else "multi-discipline"])

# ----------------------------------------------------------------------------- 4. geometry / validation / future standards
for p in sorted((RAW / "bsi_IFC4.x-specification-models/models").glob("*/*/*.ifc")):
    g("bsi-ifc4x-specification-models", str(p.relative_to(RAW / "bsi_IFC4.x-specification-models")), title=f"{p.parent.parent.name}: {p.stem}",
      building_type="component", use_cases=["geometry", "unit-test"])
GH = RAW / "ifc-gherkin-rules_testfiles/test/files"
for rule in sorted(GH.iterdir()):
    for kind in ("pass", "fail"):
        hit = sorted(rule.rglob(f"{kind}-*.ifc"))
        if hit:
            g("bsi-ifc-validation-rules", str(hit[0].relative_to(RAW / "ifc-gherkin-rules_testfiles")), title=f"Validation rule {rule.name} – {kind}",
              building_type="component", use_cases=["validation", f"validation-{kind}"], rule=rule.name, expected=kind)
for p in sorted((RAW / "bsi_IDS/Documentation/Examples").glob("*.ids")):
    g("bsi-ids", str(p.relative_to(RAW / "bsi_IDS")), title=f"IDS example – {p.stem}", use_cases=["ids", "future-standards"])
for p in sorted(x for x in (RAW / "bsi_BCF-XML/Test Cases/v3.0").rglob("*.bcf") if "unzipped" not in x.parts):
    g("bsi-bcf", str(p.relative_to(RAW / "bsi_BCF-XML")), title=f"BCF 3.0 test – {p.stem}", use_cases=["bcf", "future-standards"])
for f in ["wall-with-opening-and-window.ifcxml", "wall-with-opening-and-window_ifcxml_format.ifczip", "WallInstance_IFC4Add2_ifcspf_format.ifczip"]:
    g("ifcopenshell-files", f, title=f"Serialization sample – {f}", building_type="component", use_cases=["serialization"])

# ----------------------------------------------------------------------------- 5. DWG / DXF / PDF / Revit
LDT = "test/test-data"
for d, f in [("r9", "entities.dwg"), ("r10", "entities.dwg"), ("r11", "entities-2d.dwg"), ("r11", "entities-3d.dwg")]:
    g("libredwg-testdata", f"{LDT}/{d}/{f}", title=f"LibreDWG {d.upper()} {f}", project="libredwg-versions", use_cases=["cad-versions", "legacy-format"])
for v in ["r13", "r14", "2000", "2004", "2007", "2010", "2013", "2018"]:
    for ext in ("dwg", "dxf"):
        g("libredwg-testdata", f"{LDT}/example_{v}.{ext}", title=f"LibreDWG example drawing {v.upper()} ({ext.upper()})",
          project="libredwg-versions", use_cases=["cad-versions"])
g("libredwg-testdata", f"{LDT}/example_r12.dxf", title="LibreDWG example drawing R12 (DXF)", project="libredwg-versions", use_cases=["cad-versions"])
g("libredwg-testdata", f"{LDT}/example_2018.dxfb", title="LibreDWG example drawing 2018 (binary DXF)", project="libredwg-versions", use_cases=["cad-versions"])
ADB = SOURCES["autodesk-acad-samples"]["origin"]["base"]
for p in sorted((RAW / "autodesk_samples").glob("*.dwg")):
    bt = "industrial" if "mechanical" in p.name else "civil" if "civil" in p.name else "generic-building"
    add("autodesk-acad-samples", p, ADB + p.name, title=f"AutoCAD sample – {p.stem}", country="US", building_type=bt, use_cases=["cad-render", "real-drawing"])

AFDP_TYPE = {"ASOS_DG": "aviation", "CE_ADMIN": "office", "CE_EXPLOSIVE": "industrial", "CE_FAC_MAIN": "industrial", "CE_PEST": "industrial",
             "CONFINEMENT": "justice", "ENLISTED_DORM": "dormitory", "ENTRY_CONTROL": "security", "FIGHTER-HANGAR": "aviation",
             "FIRE_STATION": "public-safety", "FITNESS_CENTER": "sports", "INDOOR-RANGE": "sports", "KENNEL": "other", "LACCCH": "aviation",
             "LAFT": "aviation", "LAFTC": "aviation", "LAGMH": "aviation", "LAOFS": "aviation", "PERM_PARTY_ENLISTED_DORM": "dormitory",
             "SFO": "office", "SHOPS-WAREHOUSE": "industrial", "STORAGE_IGLOO": "industrial", "THULE_DORM": "dormitory",
             "VISITING_QUARTERS": "lodging", "WAREHOUSE": "industrial", "WRSS": "industrial"}
WB = SOURCES["wbdg-usaf-design-packages"]["origin"]["base"]
# removed from WBDG since download; link the Internet Archive snapshot we fetched instead (timestamp = capture time)
WAYBACK = {
    "AF/AFDP/CE_ADMIN/ce_admin_building.pdf": "20170408125937", "AF/AFDP/CE_ADMIN/ces__admin_building.rvt": "20170408125948",
    "AF/AFDP/CE_EXPLOSIVE/afdp_ce_explosive_concept_plans.pdf": "20170408130046", "AF/AFDP/CE_FAC_MAIN/concept_plans_fac_maint.pdf": "20170408130051",
    "AF/AFDP/CE_PEST/cepestmanagementprototype.pdf": "20170408130057", "AF/AFDP/FIGHTER-HANGAR/DynamicPrototypes-FighterHangarAMU.pdf": "20170408130414",
    "AF/AFDP/FIGHTER-HANGAR/DynamicPrototypes-FighterHangarAMU.rvt": "20170408130423", "AF/AFDP/SHOPS-WAREHOUSE/concept_plans_shops_warehouse.pdf": "20170408130058",
}


def wbdg_href(rel):
    rel = str(rel)
    if rel in WAYBACK:
        return f"https://web.archive.org/web/{WAYBACK[rel]}id_/https://www.wbdg.org/FFC/{urllib.parse.quote(rel)}"
    return WB + urllib.parse.quote(rel)
for p in sorted((RAW / "wbdg/AF").rglob("*")):
    if p.suffix.lower() not in (".rvt", ".pdf", ".dwg") or "AFIFS" in p.parts:
        continue
    rel = p.relative_to(RAW / "wbdg")
    folder = rel.parts[2] if rel.parts[1] == "AFDP" else "TEMPLATE"
    if rel.parts[1] == "AFBIM" and p.suffix.lower() == ".pdf":
        continue
    nm = p.stem.lower()
    disc = ["structure"] if re.search(r"(^|[-_ ])s([-_ ]|$)|struct", nm) else ["mep"] if re.search(r"(^|[-_ ])[emp]([-_ ]|$)|mech|elec|plumb|fire", nm) else ["architecture"]
    add("wbdg-usaf-design-packages", p, wbdg_href(rel), title=f"USAF {folder.replace('_', ' ').title()} – {p.stem}",
        project=f"usaf-{folder.lower()}", country="US", building_type=AFDP_TYPE.get(folder, "template"), disciplines=disc,
        use_cases=["revit-native" if p.suffix.lower() == ".rvt" else "pdf-drawing" if p.suffix.lower() == ".pdf" else "cad-render", "real-project"])
for z in sorted((RAW / "wbdg/VA/VACAD").glob("vadetails_division*.zip")):
    div = z.stem.replace("vadetails_division", "")
    pdf = z.with_suffix(".pdf")
    extra = [{"key": "pdf", "local": pdf, "href": WB + f"VA/VACAD/{pdf.name}", "media_type": "application/pdf", "roles": ["data", "overview"],
              "title": f"Division {div} details (PDF)"}] if pdf.exists() else []
    add("wbdg-va-cad-details", z, WB + f"VA/VACAD/{z.name}", title=f"VA standard details – CSI division {div} (DWG set)", project="va-cad-details",
        extra_assets=extra, country="US", building_type="healthcare", use_cases=["cad-render", "detail-drawings"], csi_division=div)

# ----------------------------------------------------------------------------- 6. Japan: CAD + PDF only
BL = SOURCES["blcj-bim-kakunin"]["origin"]["base"]
for zip_name, sub, disc in [("BLCJ_S1000_A_Revit1.zip", "A_意匠", "architecture"), ("BLCJ_S1000_S_Revit.zip", "S_構造", "structure"),
                            ("BLCJ_S1000_MEP_Revit1.zip", "MEP_設備", "mep")]:
    for pdf in sorted((CUR / "01_jp_pdf_kakunin_BLCJ_S1000" / sub).glob("*.pdf")):
        add("blcj-bim-kakunin", pdf, BL + zip_name, title=f"BLCJ S造1000㎡事務所 {sub} – {pdf.stem}", project="blcj-s1000",
            archive_member=f"{zip_name[:-4]}/{pdf.name}", country="JP", building_type="office", disciplines=[disc],
            use_cases=["jp-bim-drawing-review", "pdf-drawing"])
for f in ["木造平面例.jww", "Ａマンション平面例.jww", "Ａマンション立面例.jww", "Ａマンション25d.jww", "敷地図.jww", "日影図.jww", "天空率表.jww", "サンプル.jww"]:
    bt = "residential" if ("木造" in f or "マンション" in f) else "site"
    uc = ["jp-cad", "cad-render"] + (["jp-building-regulation"] if f in ("日影図.jww", "天空率表.jww", "敷地図.jww") else [])
    g("ezjww-jww-samples", f"jww_samples/{f}", title=f"Jw_cad sample – {f[:-4]}", project="jwcad-samples", country="JP", building_type=bt, use_cases=uc)
add("sxf-samples", RAW / "jp_cad/iku190t_ais-survey-tool/sample.sfc",
    git_href("sxf-samples", "sample.sfc", repo="iku190t/ais-survey-tool", commit="ac516c6c7a068eae2680fbfeb27455fa09a3dcd6", raw_dir="jp_cad/iku190t_ais-survey-tool"),
    title="SXF(SFC) survey drawing sample", country="JP", building_type="civil", use_cases=["jp-cad", "jp-public-works"])
add("sxf-samples", RAW / "jp_cad/allfestaboss_doboku-bench/reference/reference_t002.sfc",
    git_href("sxf-samples", "reference/reference_t002.sfc", repo="allfestaboss/doboku-bench", commit="fde87cac1893dc7adfc0023a39d8c3e39ebb490f", raw_dir="jp_cad/allfestaboss_doboku-bench"),
    title="SXF(SFC) civil reference drawing T002", country="JP", building_type="civil", use_cases=["jp-cad", "jp-public-works"])

# ----------------------------------------------------------------------------- 7. remote-only datasets (not downloaded locally)
REMOTE = [
    {"id": "tum-gni-bim.2025-bimfundamentals", "source": "tum-gni-bim", "title": "TUM GNI BIM Fundamentals – 208 student IFC models (zip)",
     "href": "https://zenodo.org/records/19722012/files/2025_BIMfundamentals.zip?download=1", "size": 503285210, "checksum_md5": None,
     "tags": dict(country="DE", building_type="mixed", use_cases=["dataset", "machine-learning"])},
    {"id": "tum-gni-bim.2026-bimprojects", "source": "tum-gni-bim", "title": "TUM GNI BIM Projects – 16 IFC (paired arch/structure, zip)",
     "href": "https://zenodo.org/records/19722012/files/2026_BIMprojects.zip?download=1", "size": 221053555, "checksum_md5": None,
     "tags": dict(country="DE", building_type="mixed", use_cases=["dataset", "multi-discipline"])},
]
