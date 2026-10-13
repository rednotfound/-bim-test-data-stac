# BIM Test Data STAC Catalog

A **static STAC 1.1.0 catalog** of publicly downloadable BIM test data: IFC (IFC2X3 / IFC4 / IFC4X3 / IFC5 alpha), DWG/DXF, PDF drawing sets, Revit, Japanese 2D CAD (Jw_cad / SXF), IDS, BCF and COBie.

- **Browse:** [open in STAC Browser](https://radiantearth.github.io/stac-browser/#/external/rednotfound.github.io/bim-test-data-stac/catalog.json)
- **Catalog root:** `https://rednotfound.github.io/bim-test-data-stac/catalog.json`
- **Flat index of all items:** `https://rednotfound.github.io/bim-test-data-stac/items.parquet` (query with DuckDB / pandas)
- **Usage and field reference:** [`stac/README.md`](stac/README.md)

**This repository does not contain or re-host any BIM data files.** Every item links to its upstream download URL (git sources are pinned to a commit) and records the license, the attribution requirement and the provenance. Thumbnails are included only for data whose license allows derivatives (`bim:license_tier = open`).

| | |
|---|---|
| Items | 562 |
| Collections (one per upstream source) | 26 |
| View dimensions | 11 (format, version, discipline, building type, country, use case, license tier, …) |
| Thumbnails | 248 |
| Upstream links checked | 544, all HTTP 200 (see `catalog/link_check.json`) |

## Repository layout

| Path | Contents |
|---|---|
| `stac/` | The STAC catalog (JSON, thumbnails, `items.parquet`). Deployed to GitHub Pages by GitHub Actions. |
| `tools/stac/` | Build scripts: `sources.py` (source and license registry), `items.py` (item list and tags), `extract.py` (metadata extraction), `thumbs.py` (thumbnails), `build_stac.py`, `check_links.py` |
| `tools/*.py` | Earlier inventory and IFC data-richness scoring scripts |
| `tools/requirements.txt` | Pinned Python dependencies |
| `catalog/` | Link-check results and the IFC data-richness score table |

Rebuilding requires local copies of the upstream data (`raw/`, `curated/`), which are not part of this repository. See the end of [`stac/README.md`](stac/README.md).

## License

- Scripts and catalog metadata in this repository: CC0-1.0 (see `stac/LICENSE`).
- Thumbnails: distributed under the license of the source data they were derived from; attribution is given in each Collection's `bim:attribution`.
- The data files themselves belong to their respective rights holders; see each Collection's `license` and `bim:license_quote`.
