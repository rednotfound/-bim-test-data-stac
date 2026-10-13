# BIM 测试数据 STAC 目录

一个**静态 STAC 1.1.0 目录**，索引可以公开下载的 BIM 测试数据：
- **IFC**：IFC2X3 / IFC4 / IFC4X3 / IFC5 alpha，以及 ifcXML、ifcZIP
- **DWG / DXF**：R9 到 R2018
- **PDF 图纸集**、**Revit (RVT)**
- **日本数据**：Jw_cad (JWW)、SXF (SFC)、BIM 图面审查样例 PDF
- **其他**：IDS、BCF、COBie

**不重新托管任何数据文件。** 每个 item 的 `data` asset 都直接指向上游原始下载地址；git 仓库的地址固定到具体 commit。本目录只包含元数据 JSON、`items.parquet`，以及许可证允许时生成的缩略图。

- 入口：`catalog.json`
- 所有 JSON 都使用相对链接，放在 GitHub Pages、R2、S3 或本地都可以直接使用。

## 结构

```
catalog.json                          根目录
├─ collections/<source>/collection.json   每个上游数据源一个 Collection（出处、许可证、署名）
│    └─ items/<item-id>/<item-id>.json     每个文件一个 Item（+ thumbnail.png）
├─ views/                             多维度视图（同一批 item 按不同维度再分组）
│    ├─ format/ format-family/ format-version/
│    ├─ discipline/ building-type/ country/
│    ├─ use-case/ license-tier/ project/ size-class/ has-thumbnail/
└─ items.parquet                      全部 item 的扁平表，可直接用 DuckDB / pandas 查询
```

## 调用方式

**浏览**：在 [STAC Browser](https://radiantearth.github.io/stac-browser/) 中打开 `catalog.json` 的公开 URL。

**Python (pystac)**

```python
import pystac
cat = pystac.Catalog.from_file("https://rednotfound.github.io/-bim-test-data-stac/catalog.json")
ifc4 = cat.get_child("views").get_child("view-format-version")   # 按版本浏览
for item in cat.get_items(recursive=True):
    p = item.properties
    if p["bim:format_family"] == "IFC" and "data-rich" in p.get("bim:use_cases", []):
        print(item.id, p["bim:format_version"], item.assets["data"].href)
```

**DuckDB（不需要服务器）**

```sql
INSTALL httpfs; LOAD httpfs;
SELECT id, bim_format_version, bim_building_type, ifc_spaces, ifc_pset_names, data_href
FROM 'https://rednotfound.github.io/-bim-test-data-stac/items.parquet'
WHERE bim_format = 'IFC-SPF' AND bim_license_tier = 'open' AND ifc_spaces > 50
ORDER BY ifc_score DESC;
```

**下载数据**：取 `assets.data.href` 即可。
- 如果有 `bim:archive_member` 字段，说明 href 是一个 zip 包，目标文件是包内的这个路径。
- 用 `file:checksum`（multihash，sha2-256）校验下载结果。如果是 zip 包内的文件，用 `bim:archive_member_checksum` 校验。

## 许可证和出处

| `bim:license_tier` | 含义 | 本目录的处理 |
|---|---|---|
| `open` | 允许再分发和修改（CC-BY、MIT、GPL、公有领域、KIT unrestricted） | 链接到上游；生成缩略图 |
| `open-nd` | 允许原样再分发，禁止修改（CC BY-ND） | 仅链接，不生成缩略图 |
| `unclear` | 发布方没有声明许可 | 仅链接，不生成缩略图 |
| `restricted` | 禁止再分发，或者没有授予再分发权 | 仅链接，不生成缩略图 |

- **Collection 层面**记录：`license`、`bim:license_quote`（许可证原文摘录）、`bim:attribution`（署名要求原文）、`providers`、`bim:origin`（仓库和 commit，或下载基地址）、`bim:retrieved`，以及 DOI（`sci:doi` 和 `cite-as` 链接）。
- **Item 层面**记录：`bim:provenance`，包括上游地址、仓库、commit、路径、是否通过 Git LFS、zip 包内路径、获取日期，以及 `rehosted: false`。
- 有 8 个 USAF 文件已从 WBDG 下架，它们的链接指向 Internet Archive 的固定快照（`web.archive.org/web/<时间戳>id_/...`），并在 provenance 中注明。
- 缩略图是对 `open` 档数据的派生作品，沿用源数据的许可证，署名见 `bim:attribution`。
- 本目录自己编写的元数据以 CC0-1.0 发布。

## 主要字段

| 字段 | 说明 |
|---|---|
| `bim:format` | IFC-SPF / IFC-ZIP / IFC-XML / IFCX / DWG / DXF / PDF / RVT / JWW / SXF / IDS / BCF / XLSX / ZIP |
| `bim:format_family` | IFC / CAD-2D / PDF / BIM-native / openBIM-exchange / COBie |
| `bim:format_version` | IFC schema、`AC1032 R2018`、`Revit 2013`、`JWW v600`、`BCF 3.0` 等 |
| `bim:disciplines` | architecture / structure / mep / infrastructure / site |
| `bim:building_type` | residential / office / healthcare / education / bridge / road / dormitory 等 |
| `bim:country` | ISO 3166-1 alpha-2（JP、US、NL、DE、NO 等） |
| `bim:use_cases` | schema-versions / parser / geometry / validation(-pass/-fail) / data-rich / multi-discipline / real-project / performance / legacy-schema / cad-versions / pdf-drawing / revit-native / jp-cad / jp-bim-drawing-review / jp-building-regulation / ids / bcf / cobie / 4d-construction 等 |
| `bim:project` | 多文件成套项目的分组，同组 item 之间互相用 `related` 链接 |
| `bim:size_class` | xs / s / m / l / xl |
| `bim:datetime_source` | `datetime` 的来源：IFC 文件头、PDF CreationDate、上游 commit 日期等 |
| `bim:location_source`, `bim:site_location_raw` | 坐标来源说明。软件默认坐标（如 Revit 的 Boston/Chicago）不写入 geometry，只保留原始值 |
| `ifc:*` | schema、view_definition、originating_system、构件数和类型、楼层/房间/区域/系统、属性集名称、属性数、工程量集、材料、分类体系、长度单位、MapConversion、完整度评分 `ifc:score` |
| `cad:*` | 版本号、图层（名称和数量）、图块、布局、实体统计、单位、范围、审计错误数 |
| `pdf:*` | 页数、图幅（A1/A3/JIS B 等，横/竖）、矢量页比例、是否可提取文字、是否含日文/中文、生成软件 |
| `rvt:*` | Revit 版本（必要时由 build 号推算）、协同模式 |
| `ids:*` / `bcf:*` / `ifcx:*` / `xlsx:*` / `archive:*` | 各格式的特有信息 |
| `file:size`, `file:checksum` | 上游文件的大小和 sha2-256 multihash |

## 重新生成

```bash
tools/.venv/bin/python -I tools/stac/check_links.py      # 检查全部上游链接和文件大小
tools/.venv/bin/python -I tools/stac/build_stac.py       # 提取元数据、生成缩略图、写出 STAC
find stac -name '*.json' -print0 | xargs -0 tools/.venv/bin/stac-validator batch
```

数据源登记表在 `tools/stac/sources.py`，条目清单和分类标签在 `tools/stac/items.py`。
