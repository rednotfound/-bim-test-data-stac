"""HEAD-check every asset href; compare Content-Length with the local copy. Writes ../../catalog/link_check.json."""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import items  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def check(a):
    r = subprocess.run(["curl", "-sIL", "-A", "Mozilla/5.0", "--max-time", "60", "-o", "/dev/null",
                        "-w", "%{http_code} %{size_download} %{url_effective}\n", a["href"]], capture_output=True, text=True)
    code = r.stdout.split()[0] if r.stdout else "000"
    if code != "200":  # some hosts (Zenodo) reject HEAD; confirm with a 1-byte ranged GET
        g = subprocess.run(["curl", "-sL", "--max-time", "60", "-r", "0-0", "-o", "/dev/null", "-w", "%{http_code}", a["href"]],
                           capture_output=True, text=True).stdout
        code = "200" if g in ("200", "206") else code
    # content-length of final response
    h = subprocess.run(["curl", "-sIL", "-A", "Mozilla/5.0", "--max-time", "60", a["href"]], capture_output=True, text=True).stdout
    lens = [l.split(":", 1)[1].strip() for l in h.splitlines() if l.lower().startswith("content-length:")]
    remote = int(lens[-1]) if lens and lens[-1].isdigit() else None
    local = Path(a["local"]).stat().st_size if not a.get("archive_member") else None
    return {"href": a["href"], "status": code, "remote_size": remote, "local_size": local,
            "size_match": None if local is None or remote is None else remote == local}


uniq = {}
for s in items.SPECS:
    for a in s["assets"]:
        uniq.setdefault(a["href"], a)
for r in items.REMOTE:
    uniq.setdefault(r["href"], {"href": r["href"], "local": __file__, "archive_member": "remote"})
with ThreadPoolExecutor(6) as ex:
    res = list(ex.map(check, uniq.values()))
(ROOT / "catalog").mkdir(exist_ok=True)
(ROOT / "catalog/link_check.json").write_text(json.dumps(res, indent=1))
bad = [r for r in res if r["status"] != "200"]
mism = [r for r in res if r["size_match"] is False]
print(f"{len(res)} urls, {len(bad)} non-200, {len(mism)} size mismatch")
for r in bad[:40] + mism[:40]:
    print(r)
