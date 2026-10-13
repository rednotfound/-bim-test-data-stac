# BIM Test Data STAC Catalog

A **static STAC 1.1.0 catalog** indexing publicly downloadable BIM test data:
- **IFC**: IFC2X3 / IFC4 / IFC4X3 / IFC5 alpha, plus ifcXML and ifcZIP
- **DWG / DXF**: R9 to R2018
- **PDF drawing sets** and **Revit (RVT)**
- **Japanese data**: Jw_cad (JWW), SXF (SFC), BIM drawing-review (BIM図面審査) sample PDFs
- **Other**: IDS, BCF, COBie

**No data files are re-hosted.** Each item's `data` asset points directly at the upstream download URL, and git sources are pinned to a specific commit. This catalog contains only metadata JSON, `items.parquet`, and thumbnails where the license allows them.

- Entry point: `catalog.json`
- All JSON files use relative links, so the catalog works unchanged on GitHub Pages, R2, S3 or a local disk.

## Structure

```
catalog.json                              root catalog
├─ collections/<source>/collection.json   one Collection per upstream source (provenance, license, attribution)
│    └─ items/<item-id>/<item-id>.json     one Item per file (+ thumbnail.png)
├─ views/                                 multi-dimensional views (the same items regrouped)
│    ├─ format/ format-family/ format-version/
│    ├─ discipline/ building-type/ country/
│    ├─ use-case/ license-tier/ project/ size-class/ has-thumbnail/
└─ items.parquet                          flat table of all items, queryable with DuckDB / pandas
```

## Usage

**Browse:** [open in STAC Browser](https://radiantearth.github.io/stac-browser/#/external/rednotfound.github.io/-bim-test-data-stac/catalog.json)

**Python (pystac)**

```python
import pystac
cat = pystac.Catalog.from_file("https://rednotfound.github.io/-bim-test-data-stac/catalog.json")
for item in cat.get_items(recursive=True):
    p = item.properties
    if p["bim:format_family"] == "IFC" and "data-rich" in p.get("bim:use_cases", []):
        print(item.id, p["bim:format_version"], item.assets["data"].href)
```

**DuckDB (no server needed)**

A static catalog has no search API. `items.parquet` is a single-file index of every item's properties, so you can filter the whole catalog with one HTTP request instead of crawling hundreds of JSON files. Column names use `_` instead of `:` (e.g. `bim:license_tier` → `bim_license_tier`).

```sql
INSTALL httpfs; LOAD httpfs;
SELECT id, bim_format_version, bim_building_type, ifc_spaces, ifc_pset_names, data_href
FROM 'https://rednotfound.github.io/-bim-test-data-stac/items.parquet'
WHERE bim_format = 'IFC-SPF' AND bim_license_tier = 'open' AND ifc_spaces > 50
ORDER BY ifc_score DESC;
```

**Downloading data:** use `assets.data.href`.
- If `bim:archive_member` is present, the href is a zip archive and the target file is at that path inside it.
- Verify downloads with `file:checksum` (multihash, sha2-256). For a file inside a zip, use `bim:archive_member_checksum`.

## Thumbnails

248 items have a `thumbnail` asset (`thumbnail.png`, max 512 px, stored next to the item JSON):

| Format | Rendering |
|---|---|
| IFC | Isometric 3D view from the south-east, material colours with simple shading (spaces, openings and annotations hidden) |
| DWG / DXF | Model space as black linework on white |
| PDF | First page |

Thumbnails are generated **only for the `open` license tier**. Every item's `bim:thumbnail` field states the outcome:
- `generated`
- `not generated: license does not allow derivatives/redistribution`: `open-nd`, `unclear` and `restricted` tiers
- `not generated: <error>`: for example, test files without geometry (`RuntimeError: no geometry`), unreadable legacy DWGs, or IFC4X3_RC2
- `not applicable`: formats with no renderer (RVT, ZIP, SXF, XLSX, IFC-ZIP, BCF)

List them with `WHERE bim_thumbnail = 'generated'` (the URL is in `thumbnail_href`), or browse `views/has-thumbnail/`.

## Licenses and provenance

| `bim:license_tier` | Meaning | Handling in this catalog |
|---|---|---|
| `open` | Redistribution and modification allowed (CC-BY, MIT, GPL, public domain, KIT unrestricted) | Link to upstream; thumbnail generated |
| `open-nd` | Verbatim redistribution allowed, no derivatives (CC BY-ND) | Link only, no thumbnail |
| `unclear` | Publisher has not stated a license | Link only, no thumbnail |
| `restricted` | Redistribution prohibited or not granted | Link only, no thumbnail |

- **Collection level:**
  - `license`
  - `bim:license_quote`: verbatim excerpt of the license
  - `bim:attribution`: verbatim attribution requirement
  - `providers`
  - `bim:origin`: repository and commit, or download base URL
  - `bim:retrieved`
  - DOI, as `sci:doi` and a `cite-as` link
- **Item level:** `bim:provenance` records:
  - upstream URL, repository, commit and path
  - whether the file is served via Git LFS
  - path inside the zip
  - retrieval date
  - `rehosted: false`
- Eight USAF files have been removed from WBDG. Their links point to pinned Internet Archive snapshots (`web.archive.org/web/<timestamp>id_/...`), noted in the provenance.
- Thumbnails are derivative works of `open`-tier data and carry the source data's license; see `bim:attribution` for attribution.
- Metadata written for this catalog is released under CC0-1.0.

## Key fields

| Field | Description |
|---|---|
| `bim:format` | IFC-SPF / IFC-ZIP / IFC-XML / IFCX / DWG / DXF / PDF / RVT / JWW / SXF / IDS / BCF / XLSX / ZIP |
| `bim:format_family` | IFC / CAD-2D / PDF / BIM-native / openBIM-exchange / COBie |
| `bim:format_version` | IFC schema, `AC1032 R2018`, `Revit 2013`, `JWW v600`, `BCF 3.0`, etc. |
| `bim:disciplines` | architecture / structure / mep / infrastructure / site |
| `bim:building_type` | residential / office / healthcare / education / bridge / road / dormitory, etc. |
| `bim:country` | ISO 3166-1 alpha-2 (JP, US, NL, DE, NO, …) |
| `bim:use_cases` | schema-versions / parser / geometry / validation(-pass/-fail) / data-rich / multi-discipline / real-project / performance / legacy-schema / cad-versions / pdf-drawing / revit-native / jp-cad / jp-bim-drawing-review / jp-building-regulation / ids / bcf / cobie / 4d-construction, etc. |
| `bim:project` | Groups the files of a multi-file project; items in the same group link to each other with `related` |
| `bim:size_class` | xs / s / m / l / xl |
| `bim:license_tier` | open / open-nd / unclear / restricted (see above) |
| `bim:thumbnail` | Whether a thumbnail was generated, and why not |
| `bim:datetime_source` | Where `datetime` comes from: IFC header, PDF CreationDate, upstream commit date, etc. |
| `bim:location_source`, `bim:site_location_raw` | Where the coordinates come from. Software-default sites (e.g. Revit's Boston/Chicago) are not written to `geometry`; the raw values are kept here |
| `ifc:*` | Schema, view definition, originating system, element counts and types, storeys / spaces / zones / systems, property set names, property count, quantity sets, materials, classification systems, length unit, MapConversion, data-richness score `ifc:score` |
| `cad:*` | Version, layers (names and count), blocks, layouts, entity statistics, units, extents, audit error count |
| `pdf:*` | Page count, paper sizes (A1 / A3 / JIS B, portrait/landscape), share of vector pages, extractable text, Japanese/Chinese text, producer |
| `rvt:*` | Revit version (estimated from the build number when needed), worksharing |
| `ids:*` / `bcf:*` / `ifcx:*` / `xlsx:*` / `archive:*` | Format-specific details |
| `file:size`, `file:checksum` | Size and sha2-256 multihash of the upstream file |

## Rebuilding

```bash
tools/.venv/bin/python -I tools/stac/check_links.py      # check all upstream links and file sizes
tools/.venv/bin/python -I tools/stac/build_stac.py       # extract metadata, render thumbnails, write STAC
find stac -name '*.json' -print0 | xargs -0 tools/.venv/bin/stac-validator batch
```

The source registry is in `tools/stac/sources.py`; the item list and classification tags are in `tools/stac/items.py`.
