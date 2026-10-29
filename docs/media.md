# Driver, car and circuit images

## Current source

The requested collection is [TracingInsights/2026/images](https://github.com/TracingInsights/2026/tree/main/images).
Pitwall downloads images at development time, rather than hotlinking at runtime.
Drivers are matched by **TLA and current constructor**, cars by constructor.
Headshots are preferred; Arvid Lindblad currently uses the matching full driver
cutout cropped to its upper square because that team has no matching headshot.
Transparency is preserved in the local WebP copies.

The source repository is Apache-2.0 and says its images originate from Formula 1.
That does not make the underlying Formula 1 images Creative Commons. Pitwall
records the exact upstream commit, original source URL, subject and resizing/crop
in `web/src/media.json` and `web/public/media/ATTRIBUTION.json`, with credits in
the footer. Venue photos have their own Commons attribution and licence records
in `web/src/race-media.json` and `web/public/media/CIRCUIT-PHOTOS.json`.

## Refresh the requested 2026 collection

Developer requirements: the normal Python environment plus Pillow.

```sh
.venv/bin/python -m pip install Pillow
.venv/bin/python -m f1fantasy.web_data
.venv/bin/python scripts/sync_tracing_images.py
# Or pin a reviewed revision instead of resolving main:
.venv/bin/python scripts/sync_tracing_images.py --ref 785e3baccd6e553e2756dad9dd8b35bb226af114
npm test --prefix web
npm run build --prefix web
```

The import validates every current-team mapping and downloads every image before
replacing the set. Source filenames are in the upstream `images/manifest.json`;
look there for headshot/car alternatives and the original Formula 1 CDN links.
Do not match only by surname or use another team's same-driver asset.

## Replace one picture with an open-licensed Commons photo

Find the driver's or car's **file page** on Wikimedia Commons. Review its licence,
author and date, and whether the clothing/livery matches your intended use.
Use the exact `File:…` title, not a Wikipedia article or a search-image URL.
The Commons importer accepts verified CC BY, CC BY-SA, CC0 or public-domain files;
it does not silently accept noncommercial, no-derivatives or unrelated licences.

Find the asset ID in `web/src/media.json`, then run, for example:

```sh
.venv/bin/python scripts/fetch_open_media.py --asset 110 \
  --file 'File:Lewis Hamilton 2016 Malaysia 2.jpg' \
  --crop '0,0,100,80'
```

Use a file title you have checked; the example is not a guarantee about that
file's availability. Crop coordinates are percentages: left, top, right, bottom.
Leave `--crop` out to keep the entire image. The importer updates that asset's
local WebP and credits, and remembers the choice in `scripts/media-overrides.json`.
Other images are retained. A later full TracingInsights import intentionally
replaces the entire driver/car set again.

For a manually supplied local image, replace `web/public/media/ID.webp` and its
matching source/author/licence/transformation record in both attribution files.
Keep accurate provenance; don't rename a different person to an existing ID.
Increment the record's revision so a published browser requests the new image.

## Layout and venue imagery

Card fitting lives in `.asset-photo`, `.official-photo` and `.car-photo` in
`web/src/style.css`. Driver portraits use contain fitting; the Commons tool can
crop a source before resizing. Cars keep their natural sideview aspect ratio.

Circuit outlines are projected from MIT-licensed `bacinger/f1-circuits` data,
not generated shapes. `web/src/visuals.js` maps GP names to circuit IDs. Venue
photos are local `web/public/media/CIRCUIT-ID.webp`; update their attribution
records when replacing them. They are archival venue illustrations, not claims
about current weather, track conditions or a live race image.
