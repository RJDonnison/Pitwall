"""Import verified open-license Commons photos and MIT circuit coordinates.

Developer-only refresh: python scripts/fetch_open_media.py (requests + Pillow).
Images are local, downscaled WebP derivatives; attribution and licences travel
with them. Wikipedia is used only to locate Commons files, never as a licence.
"""

import concurrent.futures
import html
import io
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1] / "web"
HEADERS = {
    "User-Agent": "Pitwall/1.0 open-license media importer (github.com/RJDonnison/Pitwall)"
}


def get(url, **params):
    response = requests.get(url, params=params, headers=HEADERS, timeout=40)
    response.raise_for_status()
    return response


def clean(value):
    return html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()


def main():
    assets = json.loads((ROOT / "public/forecast.json").read_text())["assets"]
    names = {
        "Nico Hulkenberg": "Nico Hülkenberg",
        "Sergio Perez": "Sergio Pérez",
        "Kimi Antonelli": "Andrea Kimi Antonelli",
        "Alexander Albon": "Alex Albon",
        "George Russell": "George Russell (racing driver)",
        "Carlos Sainz": "Carlos Sainz Jr.",
    }
    cars = {
        "Ferrari": ["Ferrari SF-26", "Ferrari SF-25"],
        "Red Bull Racing": ["Red Bull Racing RB22", "Red Bull Racing RB21"],
        "McLaren": ["McLaren MCL40", "McLaren MCL39"],
        "Mercedes": ["Mercedes W17", "Mercedes W16"],
        "Aston Martin": ["Aston Martin AMR26", "Aston Martin AMR25"],
        "Alpine": ["Alpine A526", "Alpine A525"],
        "Williams": ["Williams FW48", "Williams FW47"],
        "Racing Bulls": ["Racing Bulls VCARB 03", "Racing Bulls VCARB 02"],
        "Haas": ["Haas VF-26", "Haas VF-25"],
        "Audi": ["Audi R26"],
        "Cadillac": ["Cadillac MAC-26"],
    }
    candidates = {}
    cars["Haas F1 Team"] = cars["Haas"]
    for a in assets:
        candidates[a["id"]] = (
            [names.get(a["name"], a["name"])]
            if a["kind"] == "DRIVER"
            else cars.get(a["name"], [])
        )
    titles = list(dict.fromkeys(t for rows in candidates.values() for t in rows))
    pages, redirects = [], {}
    for offset in range(0, len(titles), 40):
        response = get(
            "https://en.wikipedia.org/w/api.php",
            action="query",
            format="json",
            prop="pageimages",
            piprop="original",
            redirects=1,
            titles="|".join(titles[offset : offset + 40]),
        ).json()
        pages.extend(response["query"]["pages"].values())
        redirects.update(
            {r["from"]: r["to"] for r in response["query"].get("redirects", [])}
        )
    by_title = {p["title"]: p for p in pages}
    for alias, title in redirects.items():
        if title in by_title:
            by_title[alias] = by_title[title]
    files, chosen = [], {}
    for a in assets:
        if a["name"] in ("Lewis Hamilton", "Kimi Antonelli"):
            file = {
                "Lewis Hamilton": "File:Lewis Hamilton 2016 Malaysia 2.jpg",
                "Kimi Antonelli": "File:Antonelli Barcelona 2024.jpg",
            }[a["name"]]
            files.append(file)
            chosen[a["id"]] = (file, a["name"])
            continue
        for title in candidates[a["id"]]:
            p = by_title.get(title)
            if p and p.get("original"):
                file = "File:" + unquote(
                    urlsplit(p["original"]["source"]).path.rsplit("/", 1)[-1]
                )
                files.append(file)
                chosen[a["id"]] = (file, title)
                break
    infos = {}
    for offset in range(0, len(files), 40):
        response = get(
            "https://commons.wikimedia.org/w/api.php",
            action="query",
            format="json",
            prop="imageinfo",
            iiprop="extmetadata|url",
            iiurlwidth=480,
            titles="|".join(files[offset : offset + 40]),
        ).json()
        for page in response["query"]["pages"].values():
            if page.get("imageinfo"):
                infos[page["title"].replace("_", " ")] = page["imageinfo"][0]
    folder = ROOT / "public/media"
    folder.mkdir(parents=True, exist_ok=True)

    def download(a):
        if a["id"] not in chosen:
            return None
        file, subject = chosen[a["id"]]
        info = infos.get(file.replace("_", " "))
        if not info:
            return None
        meta = {k: clean(v["value"]) for k, v in info["extmetadata"].items()}
        licence = meta.get("LicenseShortName", "")
        url = meta.get("LicenseUrl", "")
        allowed = (
            licence.startswith(("CC BY-SA ", "CC BY ", "CC0"))
            and ("creativecommons.org/" in url)
        ) or licence == "Public domain"
        if not allowed or any(x in licence.upper() for x in ("-NC", "-ND")):
            print("SKIP licence", a["name"], licence)
            return None
        image = ImageOps.exif_transpose(
            Image.open(io.BytesIO(get(info.get("thumburl", info["url"])).content))
        ).convert("RGB")
        image.thumbnail((480, 480))
        image.save(folder / f"{a['id']}.webp", "WEBP", quality=83)
        return a["id"], {
            "path": f"./media/{a['id']}.webp",
            "name": a["name"],
            "subject": subject,
            "author": meta.get("Attribution") or meta.get("Artist", "See source"),
            "license": licence,
            "license_url": url,
            "source": info["descriptionurl"],
            "date": meta.get("DateTimeOriginal", ""),
            "changes": "Resized and converted to WebP; original photograph may show earlier team clothing/livery.",
        }

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(download, assets):
            if result:
                results[result[0]] = result[1]
    (ROOT / "src/media.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    )
    (folder / "ATTRIBUTION.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    )
    circuits = get(
        "https://raw.githubusercontent.com/bacinger/f1-circuits/master/f1-circuits.geojson"
    ).json()
    data = [
        {
            "id": f["properties"]["id"],
            "name": f["properties"]["Name"],
            "location": f["properties"]["Location"],
            "coordinates": f["geometry"]["coordinates"],
        }
        for f in circuits["features"]
    ]
    (ROOT / "src/circuits.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    (folder / "CIRCUITS-LICENSE.txt").write_text(
        get(
            "https://raw.githubusercontent.com/bacinger/f1-circuits/master/LICENSE.md"
        ).text
    )
    print("Missing photographs:", [a["name"] for a in assets if a["id"] not in results])
    print(
        f"Imported {len(results)} licensed photographs and {len(data)} circuit layouts"
    )


if __name__ == "__main__":
    main()
