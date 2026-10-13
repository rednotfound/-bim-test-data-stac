# BIM 测试数据 STAC 目录

可公开下载的 BIM 测试数据（IFC、DWG/DXF、PDF 图纸、Revit、Jw_cad/SXF、IDS、BCF、COBie）的**静态 STAC 1.1.0 目录**。

- 目录本体：[`stac/`](stac/)，入口为 `stac/catalog.json`，使用说明见 [`stac/README.md`](stac/README.md)
- 发布后的地址：`https://<user>.github.io/<repo>/catalog.json`，可以在 [STAC Browser](https://radiantearth.github.io/stac-browser/) 中打开
- 全部条目的扁平索引：`stac/items.parquet`，可用 DuckDB / pandas 直接查询

**本仓库不包含、也不转载任何 BIM 数据文件。** 每个条目都链接到上游的原始下载地址（git 仓库固定到具体 commit），并记录许可证、署名要求和出处。只有许可证允许修改的数据（`bim:license_tier = open`）才附带缩略图。

## 仓库内容

| 路径 | 内容 |
|---|---|
| `stac/` | STAC 目录（JSON、缩略图、items.parquet），由 GitHub Actions 部署到 Pages |
| `tools/stac/` | 生成脚本：`sources.py`（数据源和许可证登记）、`items.py`（条目清单）、`extract.py`（元数据提取）、`thumbs.py`（缩略图）、`build_stac.py`、`check_links.py` |
| `tools/*.py` | 早期的数据清点和 IFC 完整度评分脚本 |
| `catalog/` | 链接检查结果、IFC 完整度评分表 |

重新生成需要本地有上游数据副本（`raw/`、`curated/`，不在仓库中），见 `stac/README.md` 末尾。

## 许可证

- 本仓库的脚本和元数据：CC0-1.0（见 `stac/LICENSE`）
- 缩略图：沿用对应源数据的许可证，署名见各 Collection 的 `bim:attribution`
- 数据文件本身：归各自的权利人所有，许可证见各 Collection
