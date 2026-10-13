"""Thumbnail rendering (PNG, max 512 px). Only called for license_tier == "open" sources."""
import multiprocessing
from pathlib import Path

import numpy as np

SIZE = 512


def pdf_thumb(src: Path, out: Path):
    import pymupdf
    with pymupdf.open(src) as d:
        page = d[0]
        zoom = SIZE / max(page.rect.width, page.rect.height)
        page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).save(out)


def cad_thumb(doc, out: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration, ColorPolicy
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    fig = plt.figure(figsize=(SIZE / 100, SIZE / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.BLACK, max_flattening_distance=1)
    Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=True)
    fig.savefig(out, dpi=100, facecolor="white")
    plt.close(fig)


def ifc_thumb(src: Path, out: Path, max_tris=400_000):
    import ifcopenshell
    import ifcopenshell.geom
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection

    f = ifcopenshell.open(str(src))
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    it = ifcopenshell.geom.iterator(s, f, min(8, multiprocessing.cpu_count()), exclude=("IfcSpace", "IfcOpeningElement", "IfcAnnotation"))
    tris, cols = [], []
    if it.initialize():
        while True:
            sh = it.get()
            g = sh.geometry
            v = np.asarray(g.verts, dtype=float).reshape(-1, 3)
            fa = np.asarray(g.faces, dtype=np.int64).reshape(-1, 3)
            if len(fa):
                mids = np.asarray(g.material_ids, dtype=np.int64) if len(g.material_ids) == len(fa) else None
                mats = g.materials
                rgb = np.full((len(fa), 3), 0.75)
                if mids is not None and len(mats):
                    pal = np.array([[m.diffuse.r(), m.diffuse.g(), m.diffuse.b()] if hasattr(m.diffuse, "r") else list(m.diffuse)[:3] for m in mats])
                    ok = mids >= 0
                    rgb[ok] = pal[mids[ok]]
                tris.append(v[fa])
                cols.append(rgb)
            if not it.next():
                break
    if not tris:
        raise RuntimeError("no geometry")
    T = np.concatenate(tris)
    C = np.concatenate(cols)
    if len(T) > max_tris:
        idx = np.random.default_rng(0).choice(len(T), max_tris, replace=False)
        T, C = T[idx], C[idx]
    # isometric view from south-east, z up
    az, el = np.radians(-45), np.radians(30)
    R = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az) * np.sin(el), np.cos(az) * np.sin(el), np.cos(el)],
                  [np.sin(az) * np.cos(el), np.cos(az) * np.cos(el), -np.sin(el)]])
    P = T @ R.T
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    light = np.array([0.4, -0.5, 0.75])
    light /= np.linalg.norm(light)
    shade = 0.45 + 0.55 * np.abs(n @ light)
    order = np.argsort(-P[:, :, 2].mean(axis=1))  # far to near
    fig = plt.figure(figsize=(SIZE / 100, SIZE / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.add_collection(PolyCollection(P[order][:, :, :2], facecolors=np.clip(C[order] * shade[order, None], 0, 1), edgecolors="none", antialiaseds=False))
    lo, hi = P[:, :, :2].reshape(-1, 2).min(0), P[:, :, :2].reshape(-1, 2).max(0)
    pad = (hi - lo).max() * 0.04
    span = (hi - lo).max() / 2 + pad
    c = (lo + hi) / 2
    ax.set_xlim(c[0] - span, c[0] + span)
    ax.set_ylim(c[1] - span, c[1] + span)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(out, dpi=100, facecolor="white")
    plt.close(fig)


def main(argv):
    """CLI so the builder can run each render in a subprocess with a timeout: thumbs.py SRC OUT."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    src, out = Path(argv[1]), Path(argv[2])
    ext = src.suffix.lower()
    if ext == ".pdf":
        pdf_thumb(src, out)
    elif ext == ".ifc":
        ifc_thumb(src, out)
    elif ext in (".dwg", ".dxf", ".dxfb"):
        from extract import dwg_meta, dxf_meta
        _, doc = (dwg_meta if ext == ".dwg" else dxf_meta)(src, keep_doc=True)
        if doc is None:
            raise SystemExit("unreadable")
        cad_thumb(doc, out)
    elif ext == ".sfc":
        raise SystemExit("no renderer")
    else:
        raise SystemExit(f"no renderer for {ext}")


if __name__ == "__main__":
    import sys
    main(sys.argv)
