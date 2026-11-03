# Driver, car and circuit images

## Current source

The requested collection is [TracingInsights/2026/images](https://github.com/TracingInsights/2026/tree/main/images).
Pitwall keeps local copies for the bundled roster and discovers missing or changed
driver and team images dynamically from the same collection's `images/manifest.json`.
Drivers are matched by **TLA and current constructor**, cars by constructor name;
images do not depend on a hard-coded Fantasy asset ID.
Headshots are preferred; Arvid Lindblad currently uses the matching full driver
cutout cropped to its upper square because that team has no matching headshot.
Transparency is preserved in the local WebP copies. New matches load directly from
the collection's GitHub-hosted files. For example, a Haas roster entry for Ryo
Hirakawa (`HIR`) automatically selects `drivers/Haas F1 Team/HIR.webp`.

The source repository is Apache-2.0 and says its images originate from Formula 1.
That does not make the underlying Formula 1 images Creative Commons. For bundled
files, Pitwall records the exact upstream commit, source URL, subject and resizing/crop
in `web/src/media.json` and `web/public/media/ATTRIBUTION.json`, with credits in
the footer. Venue photos have their own Commons attribution and licence records
in `web/src/race-media.json` and `web/public/media/CIRCUIT-PHOTOS.json`.

## Automatic discovery and refresh

Each accepted forecast dataset triggers one manifest request, shared across all
its drivers and constructors. Matching bundled images stay local; new identities,
constructor changes or changed source records use the discovered image. A response
for an older roster cannot overwrite a newer roster's images. Discovery runs
without blocking forecasts, transfers or optimization.

Headshots take precedence over driver cutouts for the same team. Tall cutouts are
cropped to their upper square in CSS; car sideviews retain contain fitting.
Ambiguous or unavailable matches use the existing helmet/car placeholder rather
than a different team's picture. Failed image downloads also restore that placeholder.

The footer adds discovered images' original Formula 1 URLs, upstream file links,
rights and display transformations. Bundled records retain pinned commit links;
dynamic records explicitly link the live source collection rather than claiming a
pinned revision. `web/public/media/ATTRIBUTION.json` describes the bundled files.

## Maintain a bundled image

For a local image, replace `web/public/media/ID.webp` and its
matching source/author/licence/transformation record in both attribution files.
Keep accurate provenance; don't rename a different person to an existing ID.
Increment the record's revision so a published browser requests the new image.
Match the upstream manifest's original source and file path in its provenance
record to keep serving the bundled copy when that image is rediscovered.

## Layout and venue imagery

Card fitting lives in `.asset-photo`, `.official-photo` and `.car-photo` in
`web/src/style.css`. Driver portraits use contain fitting; the Commons tool can
crop a source before resizing. Cars keep their natural sideview aspect ratio.

The five remaining circuit sector maps are clean transparent SVG surfaces extracted
from the official 2026 maps listed in `web/src/track-guides.json`. Sector text gaps
are joined locally; labels, activation markers and background are omitted. Full
original maps remain linked. `python -m f1fantasy.circuit_maps` regenerates
`web/src/sector-maps.json` from the local credited WebPs, without network access.
Other circuit outlines are projected from MIT-licensed `bacinger/f1-circuits` data,
not generated shapes. `web/src/visuals.js` maps GP names to circuit IDs. Venue
photos are local `web/public/media/CIRCUIT-ID.webp`; update their attribution
records when replacing them. They are archival venue illustrations, not claims
about current weather, track conditions or a live race image.
