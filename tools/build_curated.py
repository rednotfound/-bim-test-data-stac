"""Copy a small, typical test set from raw/ into curated/ and write MANIFEST.csv.

Every entry is listed explicitly so the set stays small and reproducible.
Usage: tools/.venv/bin/python -I tools/build_curated.py
"""
import csv
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
OUT = ROOT / "curated"

LIC_BSI = "buildingSMART, MIT/CC-BY-4.0"
LIC_BLCJ = "BLCJ・建築設計三会 著作権 / 无授权不可再分发（仅内部测试）"
LIC_PD = "US Government work, public domain"

SIMPLE_SCENE = ["Building-Architecture", "Building-Structural", "Building-Hvac",
                "Building-Landscaping", "Infra-Road", "Infra-Bridge", "Infra-Rail",
                "Infra-Plumbing", "Infra-Electrical", "Infra-Landscaping"]

# (source path under raw/, target path under curated/, source name, license, note)
ENTRIES = []


def add(src, dst, source, lic, note=""):
    ENTRIES.append((src, dst, source, lic, note))


# 01 日本 BIM 确认申请 图纸（BLCJ S造1000㎡事务所）: 只取 PDF, from zip
BLCJ = [
    ("blcj_jp/BLCJ_S1000_A_Revit1.zip", "A_意匠", ["Revit_BIM申請サンプルモデル_01.pdf",
                                                  "03_別紙2_BIM図面審査における入出力基準適合申告書（初版）R08_03版(001)_意匠Revit.pdf"]),
    ("blcj_jp/BLCJ_S1000_S_Revit.zip", "S_構造", ["S_構造モデル_260319修正分.pdf",
                                                 "S_構造モデル_SS7_構造計算書-結果(BIM申請サンプル).pdf"]),
    ("blcj_jp/BLCJ_S1000_MEP_Revit1.zip", "MEP_設備", ["BLCJsample_E_Revit_01.pdf", "BLCJsample_M_Revit_01.pdf"]),
]

# 02 同一场景 × 4 个 IFC 版本
for s in SIMPLE_SCENE:
    add(f"bsi_Sample-Test-Files/IFC 2.3.0.1 (IFC 2x3 TC1)/Simple-Scene/{s}.ifc", f"02_ifc_versions_same_scene/IFC2X3/{s}.ifc", "buildingSMART Sample-Test-Files", LIC_BSI)
    add(f"bsi_Sample-Test-Files/IFC 4.0.2.1 (IFC 4 ADD2 TC1)/Simple-Scene/{s}.ifc", f"02_ifc_versions_same_scene/IFC4/{s}.ifc", "buildingSMART Sample-Test-Files", LIC_BSI)
    add(f"bsi_Sample-Test-Files/IFC 4.3.2.0 (IFC 4.3 ADD2)/Simple-Scene/{s}.ifc", f"02_ifc_versions_same_scene/IFC4X3_ADD2/{s}.ifc", "buildingSMART Sample-Test-Files", LIC_BSI)
    add(f"bsi_IFC5-development/examples/PCERT-Sample-Scene/{s}.ifcx", f"02_ifc_versions_same_scene/IFC5_alpha/{s}.ifcx", "buildingSMART IFC5-development", LIC_BSI, "IFC5 alpha (JSON)")

# 03 经典建筑模型
add("steptools_ifc/AC20-FZK-Haus.ifc", "03_ifc_classic_buildings/KIT_AC20-FZK-Haus_IFC4.ifc", "KIT (via steptools)", "KIT, free for research/testing", "最经典的小住宅")
add("steptools_ifc/AC20-Institute-Var-2.ifc", "03_ifc_classic_buildings/KIT_AC20-Institute-Var-2_IFC4.ifc", "KIT (via steptools)", "KIT, free for research/testing", "办公/研究所")
add("steptools_ifc/KIT-Simple-Road-Test-Web-IFC4x3_RC2.ifc", "03_ifc_classic_buildings/KIT_Simple-Road_IFC4X3_RC2.ifc", "KIT (via steptools)", "KIT, free for research/testing", "道路/基础设施")
DUP = "bsi_Community-Sample-Test-Files/IFC 2.3.0.1 (IFC 2x3)/Duplex Apartment"
for f, n in [("Duplex_A_20110907.ifc", "建筑"), ("Duplex_M_20111024_ROOMS_AND_SPACES.ifc", "暖通+房间/空间"),
             ("Duplex_MEP_20110907.ifc", "机电"), ("Duplex_Plumbing_20121113.ifc", "给排水"), ("Duplex_Electrical_20121207.ifc", "电气")]:
    add(f"{DUP}/{f}", f"03_ifc_classic_buildings/NIBS_Duplex_multi-discipline_IFC2X3/{f}", "NIBS Common BIM Files", "NIBS, open use", f"多专业成套: {n}")
add(f"{DUP}/2012-03-23-Duplex-Handover.xlsx", "03_ifc_classic_buildings/NIBS_Duplex_multi-discipline_IFC2X3/Duplex_COBie_Handover.xlsx", "NIBS Common BIM Files", "NIBS, open use", "COBie 交付表")
add("DataSetSchependomlaan/Design model IFC/IFC Schependomlaan.ifc", "03_ifc_classic_buildings/Schependomlaan_design_IFC2X3.ifc", "Schependomlaan dataset (TU/e)", "科研/学术用途许可", "真实住宅项目")
add("DataSetSchependomlaan/Design model IFC/ROOT-Compleet interne modelkwaliteit.bcfzip", "03_ifc_classic_buildings/Schependomlaan_issues.bcfzip", "Schependomlaan dataset (TU/e)", "科研/学术用途许可", "对应模型的 BCF 问题单")

# 04 新标准/未来: IFC5 / IDS / BCF3 / ifcXML / ifcZIP
add("bsi_IFC5-development/examples/IFC Hero Model/IFC Hero Model.ifc", "04_future_standards/IFC5_HeroModel/IFC_Hero_Model_IFC4.ifc", "buildingSMART IFC5-development", LIC_BSI, "与 .ifcx 同模型")
add("bsi_IFC5-development/examples/IFC Hero Model/IFC Hero Model.ifcx", "04_future_standards/IFC5_HeroModel/IFC_Hero_Model.ifcx", "buildingSMART IFC5-development", LIC_BSI)
add("bsi_IDS/Documentation/Examples/IDS_SimpleBIM_examples.ids", "04_future_standards/IDS/IDS_SimpleBIM_examples.ids", "buildingSMART IDS", LIC_BSI, "IDS 1.0 模型检查规则")
add("bsi_IDS/Documentation/Examples/IDS_ArcDox.ids", "04_future_standards/IDS/IDS_ArcDox.ids", "buildingSMART IDS", LIC_BSI)
add("bsi_BCF-XML/Test Cases/v3.0/Visualization/Single visible wall/single visible wall.bcf", "04_future_standards/BCF3/single_visible_wall.bcf", "buildingSMART BCF-XML", LIC_BSI)
add("bsi_BCF-XML/Test Cases/v3.0/Visualization/Perspective camera/perspective camera.bcf", "04_future_standards/BCF3/perspective_camera.bcf", "buildingSMART BCF-XML", LIC_BSI)
add("ifcopenshell_files/wall-with-opening-and-window.ifcxml", "04_future_standards/serializations/wall-with-opening-and-window.ifcxml", "IfcOpenShell files", "LGPL/test data", "ifcXML 序列化")
add("ifcopenshell_files/wall-with-opening-and-window_ifcxml_format.ifczip", "04_future_standards/serializations/wall-with-opening-and-window.ifczip", "IfcOpenShell files", "LGPL/test data", "ifcZIP 序列化")

# 09 IFC 几何/概念用例（buildingSMART IFC4.x 规范示例，每种表达一个小文件）
for spec in sorted((RAW / "bsi_IFC4.x-specification-models/models").glob("*/*/*.ifc")):
    rel = spec.relative_to(RAW)
    add(str(rel), f"09_ifc_geometry_cases/{spec.parent.parent.name}/{spec.name}", "buildingSMART IFC4.x-specification-models", LIC_BSI, "规范示例")

# 10 IFC 校验用例（buildingSMART 校验服务规则测试，每条规则 1 pass + 1 fail）
for rule in sorted((RAW / "ifc-gherkin-rules_testfiles/test/files").iterdir()):
    for kind in ("pass", "fail"):
        hit = sorted(rule.rglob(f"{kind}-*.ifc"))
        if hit:
            add(str(hit[0].relative_to(RAW)), f"10_ifc_validation_cases/{rule.name}/{hit[0].name}", "buildingSMART ifc-gherkin-rules", "MIT", f"规则 {rule.name} 的 {kind} 用例")

# 11 数据最全的 IFC（按 catalog/ifc_richness.csv 打分挑选：属性集/工程量/房间/材料/分类/系统）
RICH = "11_ifc_data_rich"
WIT = "web-ifc_tests/tests/ifcfiles/public"
LIC_WIT = "web-ifc 公开测试集 (MPL-2.0 repo)，原始版权归模型作者"
add(f"{WIT}/ISSUE_068_ARK_NUS_skolebygg.ifc", f"{RICH}/IFC2X3_Norway_school_ARK.ifc", "web-ifc tests", LIC_WIT, "得分第1: 307房间/75种Pset/436分类引用")
add("duraark/_extracted/NBS_Lakeside_ifc/NBS_Lakeside/NBS_LakesideAC01_Arch.ifc", f"{RICH}/IFC2X3_NBS_Lakeside_Archicad.ifc", "DURAARK (TIB)", "DURAARK 数据集，用途见 TIB 条款", "英国 NBS 示范楼；同楼另有 Revit/Vectorworks 导出版在 raw/duraark")
add("yousheng_IfcSampleFiles/Ifc4_Revit_ARC.ifc", f"{RICH}/IFC4_Revit_project/Ifc4_Revit_ARC.ifc", "youshengCode/IfcSampleFiles", "repo 未声明许可", "同项目 建筑")
add("yousheng_IfcSampleFiles/Ifc4_Revit_MEP.ifc", f"{RICH}/IFC4_Revit_project/Ifc4_Revit_MEP.ifc", "youshengCode/IfcSampleFiles", "repo 未声明许可", "同项目 机电：340 个系统/区域")
add("auckland_openifc/20160125Trapelo_Design_Intent.ifc", f"{RICH}/IFC4_Trapelo_office.ifc", "Open IFC Model Repository (Auckland)", "Auckland 仓库，未声明许可", "3163 个分类引用(OmniClass/Uniformat)")
add("auckland_openifc/20210215IFC4_RV_Convenience_store_Renga_4.5.ifc", f"{RICH}/IFC4_RV_Convenience_store_Renga.ifc", "Open IFC Model Repository (Auckland)", "Auckland 仓库，未声明许可", "构件类型最多(37种)，IFC4 Reference View")
add(f"{WIT}/ISSUE_159_kleine_Wohnung_R22.ifc", f"{RICH}/IFC4_small_apartment_Archicad.ifc", "web-ifc tests", LIC_WIT, "小户型，每构件属性最多")
add("bsi_IFC5-development/examples/Road/Roadway_project_IFC4X3.ifc", f"{RICH}/IFC4X3_Roadway_project.ifc", "buildingSMART IFC5-development", LIC_BSI, "道路（线形/路面/设施）")
add(f"{WIT}/Viadotto Acerno.ifc", f"{RICH}/IFC4X3_Viadotto_Acerno_bridge.ifc", "web-ifc tests", LIC_WIT, "高架桥，7000+ 构件")
add("BIMvoice_ifcsamples/IFC4x3/Klassiqua-Office-Archetypes/2026-07_Klassiqua_Office_Archetype_Construction_Year_2026.ifc", f"{RICH}/IFC4X3_Klassiqua_office_2026.ifc", "BIMvoice/Klassiqua", "CC-BY-4.0", "IFC4.3 建筑")
add("opensourceBIM_TestFiles/TestData/data/Allplan-Smiley-West.ifc", "03_ifc_classic_buildings/legacy_IFC2X_FINAL_Smiley-West.ifc", "opensourceBIM TestFiles (KIT)", "KIT, free for research/testing", "旧版 schema(IFC2x)，兼容性测试")

# 05 DWG/DXF 全版本
LDT = "libredwg_testdata/test/test-data"
add(f"{LDT}/r9/entities.dwg", "05_dwg_dxf_versions/DWG_R9_AC1004.dwg", "LibreDWG test-data", "GPL-3.0 test data")
add(f"{LDT}/r10/entities.dwg", "05_dwg_dxf_versions/DWG_R10_AC1006.dwg", "LibreDWG test-data", "GPL-3.0 test data")
add(f"{LDT}/r11/entities-2d.dwg", "05_dwg_dxf_versions/DWG_R11-12_AC1009.dwg", "LibreDWG test-data", "GPL-3.0 test data")
for v, tag in [("r13", "R13_AC1012"), ("r14", "R14_AC1014"), ("2000", "R2000_AC1015"), ("2004", "R2004_AC1018"),
               ("2007", "R2007_AC1021"), ("2010", "R2010_AC1024"), ("2013", "R2013_AC1027"), ("2018", "R2018_AC1032")]:
    add(f"{LDT}/example_{v}.dwg", f"05_dwg_dxf_versions/DWG_{tag}.dwg", "LibreDWG test-data", "GPL-3.0 test data", "同一图纸的各版本")
    add(f"{LDT}/example_{v}.dxf", f"05_dwg_dxf_versions/DXF_{tag}.dxf", "LibreDWG test-data", "GPL-3.0 test data", "同一图纸的各版本")
add(f"{LDT}/example_r12.dxf", "05_dwg_dxf_versions/DXF_R12_AC1009.dxf", "LibreDWG test-data", "GPL-3.0 test data")
add(f"{LDT}/example_2018.dxfb", "05_dwg_dxf_versions/DXF_R2018_binary.dxfb", "LibreDWG test-data", "GPL-3.0 test data", "二进制 DXF")

# 06 真实 DWG 图纸 + 对应 PDF
AD = "autodesk_samples"
for f, n in [("architectural_example-imperial.dwg", "建筑"), ("civil_example-imperial.dwg", "土木"),
             ("mechanical_example-imperial.dwg", "机械"), ("blocks_and_tables_-_metric.dwg", "图块/表格(公制)"),
             ("title_block-iso.dwg", "ISO 图框"), ("architectural_-_annotation_scaling_and_multileaders.dwg", "注释比例/多重引线")]:
    add(f"{AD}/{f}", f"06_dwg_real_drawings/Autodesk_{f}", "Autodesk AutoCAD sample files", "Autodesk sample (free download)", n)
TH = "wbdg/AF/AFDP/THULE_DORM"
add(f"{TH}/Thule Bldg 1-Officer & Cont Mgr 48.dwg", "06_dwg_real_drawings/USAF_Thule_Bldg1/Thule_Bldg1.dwg", "WBDG USAF Design Package", LIC_PD, "DWG↔PDF 同一图纸")
add(f"{TH}/Thule_Bldg_1_-_Officer_&_Contractor_Managers_48.pdf", "06_dwg_real_drawings/USAF_Thule_Bldg1/Thule_Bldg1.pdf", "WBDG USAF Design Package", LIC_PD, "DWG↔PDF 同一图纸")

# 07 PDF 图纸集（矢量 PDF）
add(f"{TH}/ArchitectureSheets_v1.0.pdf", "07_pdf_drawing_sets/USAF_Dorm_Architecture_Sheets.pdf", "WBDG USAF Design Package", LIC_PD, "Revit 出图的矢量 PDF")
add(f"{TH}/StructuralSheets_v1.0.pdf", "07_pdf_drawing_sets/USAF_Dorm_Structural_Sheets.pdf", "WBDG USAF Design Package", LIC_PD)
add(f"{TH}/PlumbingSheets_v1.0.pdf", "07_pdf_drawing_sets/USAF_Dorm_Plumbing_Sheets.pdf", "WBDG USAF Design Package", LIC_PD)

# 08 日本 2D CAD: Jw_cad (JWW) / SXF (SFC)
JW = "jp_cad/monozukuri-ai_ezjww/jww_samples"
for f in ["木造平面例.jww", "Ａマンション平面例.jww", "Ａマンション立面例.jww", "Ａマンション25d.jww",
          "敷地図.jww", "日影図.jww", "天空率表.jww", "サンプル.jww"]:
    add(f"{JW}/{f}", f"08_jp_2d_cad/JWW/{f}", "ezjww repo (Jw_cad 样例)", "repo MIT；原始图纸来自 Jw_cad 附带样例", "Jw_cad")
add("jp_cad/iku190t_ais-survey-tool/sample.sfc", "08_jp_2d_cad/SXF/sample_survey.sfc", "ais-survey-tool", "AGPL-3.0 repo", "SXF(SFC) 测量图")
add("jp_cad/allfestaboss_doboku-bench/reference/reference_t002.sfc", "08_jp_2d_cad/SXF/doboku_reference_t002.sfc", "doboku-bench", "MIT", "SXF(SFC) 土木小图")


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    rows = []
    for zpath, sub, members in BLCJ:
        with zipfile.ZipFile(RAW / zpath) as z:
            names = {Path(n.encode("cp437").decode("cp932") if not (i.flag_bits & 0x800) else n).name: i
                     for i in z.infolist() for n in [i.filename]}
            for m in members:
                info = names[m]
                dst = OUT / "01_jp_pdf_kakunin_BLCJ_S1000" / sub / m
                dst.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(dst, "wb") as out:
                    shutil.copyfileobj(src, out)
                rows.append((str(dst.relative_to(OUT)), dst.stat().st_size, "BLCJ BIM図面審査サンプル S造1000㎡事務所",
                             LIC_BLCJ, "日本确认申请图 PDF"))
    missing = []
    for src, dst, source, lic, note in ENTRIES:
        s = RAW / src
        if not s.exists() or s.stat().st_size < 200:
            missing.append(src)
            continue
        d = OUT / dst
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        rows.append((dst, d.stat().st_size, source, lic, note))
    with open(OUT / "MANIFEST.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["path", "size_bytes", "source", "license", "note"])
        w.writerows(sorted(rows))
    total = sum(r[1] for r in rows)
    print(f"{len(rows)} files, {total / 1e6:.1f} MB")
    if missing:
        print("MISSING:", *missing, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
