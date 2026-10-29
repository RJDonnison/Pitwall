"""Import the requested TracingInsights 2026 headshots and car images locally.

Run after generating forecast.json: python scripts/sync_tracing_images.py.
Requires requests and Pillow. Pins the source commit and preserves provenance;
the official Formula 1 source images are not represented as Creative Commons.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageOps
import requests

ROOT = Path(__file__).resolve().parents[1] / "web"
REPO = "TracingInsights/2026"


def get(url):
    response = requests.get(
        url, timeout=45, headers={"User-Agent": "Pitwall-media-importer/1.0"}
    )
    response.raise_for_status()
    return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref", default="main", help="Upstream commit, release or branch"
    )
    args = parser.parse_args()
    revision = get(
        f"https://api.github.com/repos/{REPO}/commits/{quote(args.ref, safe='')}"
    ).json()["sha"]
    base = f"https://raw.githubusercontent.com/{REPO}/{revision}"
    license_text = get(base + "/LICENSE").text.replace("\r\n", "\n")
    manifest = get(base + "/images/manifest.json").json()
    assets = json.loads((ROOT / "public/forecast.json").read_text())["assets"]
    constructors = {
        a["team_id"]: a["name"] for a in assets if a["kind"] == "CONSTRUCTOR"
    }
    folder = ROOT / "public/media"
    jobs = []
    for a in assets:
        team = constructors[a["team_id"]]
        if a["kind"] == "CONSTRUCTOR":
            matches = [r for r in manifest["cars"] if r["team"] == team]
        else:
            matches = [
                r
                for r in manifest["headshots"]
                if r["driver"] == a["tla"] and r["team"] == team
            ]
        if a["kind"] == "DRIVER" and not matches:
            matches = [
                r
                for r in manifest["drivers"]
                if r["driver"] == a["tla"] and r["team"] == team
            ]
        if len(matches) != 1:
            raise ValueError(
                f"No unique current-team source image: {a['name']} / {team}"
            )
        jobs.append((a, matches[0]))

    def convert(job):
        a, row = job
        path = "images/" + quote(row["file"], safe="/")
        image = ImageOps.exif_transpose(
            Image.open(io.BytesIO(get(base + "/" + path).content))
        ).convert("RGBA")
        cropped = a["kind"] == "DRIVER" and row["file"].startswith("drivers/")
        if cropped:
            image = image.crop((0, 0, image.width, min(image.height, image.width)))
        image.thumbnail((1000, 400) if a["kind"] == "CONSTRUCTOR" else (400, 400))
        buffer = io.BytesIO()
        image.save(buffer, "WEBP", quality=90)
        metadata = {
            "path": f"./media/{a['id']}.webp",
            "name": a["name"],
            "subject": a["name"]
            + (" · 2026 car" if a["kind"] == "CONSTRUCTOR" else " · 2026 portrait"),
            "author": "Formula 1 · distributed by TracingInsights",
            "license": "Upstream repository: Apache-2.0; source imagery: Formula 1",
            "license_url": f"https://github.com/{REPO}/blob/{revision}/LICENSE",
            "source": row["source"],
            "repository": f"https://github.com/{REPO}/blob/{revision}/{path}",
            "revision": revision,
            "date": "2026 season imagery",
            "changes": (
                "Upper-body crop from the matched driver cutout; " if cropped else ""
            )
            + "Downscaled and converted to WebP; transparency preserved. Not Creative Commons.",
        }
        return a["id"], buffer.getvalue(), metadata

    # Validate every mapping and download before replacing the existing set.
    with ThreadPoolExecutor(max_workers=3) as pool:
        converted = list(pool.map(convert, jobs))
    result = {}
    for id, content, metadata in converted:
        (folder / f"{id}.webp").write_bytes(content)
        result[id] = metadata
    (ROOT / "src/media.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    )
    (folder / "ATTRIBUTION.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    )
    (folder / "TRACINGINSIGHTS-LICENSE.txt").write_text(license_text)
    print(
        f"Imported {len(result)} matched headshots/cars from {REPO}@{revision}; no external image requests at runtime"
    )


if __name__ == "__main__":
    main()
