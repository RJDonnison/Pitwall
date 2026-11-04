# Images and attribution

## Driver and constructor images

Pitwall displays driver and constructor images directly from raw GitHub URLs in the season's TracingInsights collection, currently [TracingInsights/2026/images](https://github.com/TracingInsights/2026/tree/main/images). It checks `images/manifest.json` for new drivers, team changes and newly recognized constructors.

Drivers are matched by TLA and current constructor. Constructors are matched by team name. The match does not depend on a Fantasy asset ID. Pitwall prefers a headshot, then a matching driver cutout cropped to the upper square. Car side views keep their transparent background and natural aspect ratio. Ambiguous or failed matches use the built-in placeholder rather than another team's image.

Known 2026 matches use their pinned upstream commit until a changed manifest record is found. New matches load from the live collection. A 2027 forecast requests the 2027 collection; an unpublished collection produces placeholders rather than old-season clothing. One manifest request is shared across an accepted forecast roster, and an older roster response cannot replace a newer one.

Current circuit guides use the photograph and detailed-map URLs published on Formula 1's official season pages. Older venue photographs, heroes and detailed maps remain available through raw GitHub links pinned to published commit `1e09f384d3d2a3ad09823024f17f51e9e22fc622`. The downloaded image copies have been removed from the working tree and deployment; only attribution and license records remain in `web/public/media`. Maps and interface icons drawn as inline SVG remain part of the page.

## Rights and records

The TracingInsights repository uses Apache-2.0 and identifies Formula 1 as the source of its images. That repository license does not make the underlying Formula 1 images Creative Commons.

Bundled provenance is recorded in:

- `web/src/media.json`
- `web/public/media/ATTRIBUTION.json`

Each record includes the source, subject, upstream path, pinned commit where applicable and any crop or resize. Dynamic records link to the live upstream collection rather than claiming a pinned revision. Credits are shown in the site footer.

Venue photographs have separate Commons records in `web/src/race-media.json` and `web/public/media/CIRCUIT-PHOTOS.json`. Circuit outlines and sector maps retain their own source information. These images illustrate the venue; they do not show current weather or track conditions.

## Update a pinned image

1. Verify the person or car, current constructor and upstream collection path.
2. Update the matching repository URL, source and pinned commit in `web/src/media.json` and `web/public/media/ATTRIBUTION.json`.
3. Record any crop and increment the record revision.

The browser uses the upstream repository URL, so no local derivative is needed. Do not relabel a different person or car under an existing ID, and preserve transparency where the source has it. Attribution records retain the historical derivative names for provenance.

## Circuit images

The daily history refresh discovers circuit pages through the official season calendar. It stores current specifications, descriptions, source dates and remote artwork URLs in `history.json`; it never downloads the image files. Both the strategy page and race deep dive use this published information, including for new circuits.

The browser loads each official detailed map and extracts its three coloured road surfaces. It removes annotations and filled legend boxes, bridges small label gaps and draws the result as transparent SVG in the same pink, gold and cyan palette and viewport as the existing maps. Geometry is shared in memory between views of the same map URL. An unreadable map or missing sector produces an unavailable message and retains the full-map link; it does not substitute an invented layout. Existing guides and committed geometry remain fallbacks when current metadata is absent. Other circuit outlines use the MIT-licensed `bacinger/f1-circuits` coordinates.

Remote images use the browser's normal HTTP cache according to the source server's headers. This is separate from the in-memory geometry cache; there is no offline image mirror or service worker. Updated URLs use new cache entries, while reopening an unchanged map can reuse its existing image and geometry.

Regenerating the legacy fallback `web/src/sector-maps.json` remains a manual operation. First obtain the credited source maps and place them at the paths listed in `web/src/track-guides.json`, then run:

```sh
python -m f1fantasy.circuit_maps
```

Builds and GitHub Actions publish metadata and remote URLs, without downloading or regenerating image files. The browser processes a map when it is displayed. A browser test checks that deployment media contains no downloaded image copies. Formula 1 source links are shown beside current maps; the existing Commons and pinned-image credits remain in the footer.
