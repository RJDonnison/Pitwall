# Images and attribution

## Driver and constructor images

Pitwall displays driver and constructor images directly from raw GitHub URLs in the season's TracingInsights collection, currently [TracingInsights/2026/images](https://github.com/TracingInsights/2026/tree/main/images). It checks `images/manifest.json` for new drivers, team changes and newly recognized constructors.

Drivers are matched by TLA and current constructor. Constructors are matched by team name. The match does not depend on a Fantasy asset ID. Pitwall prefers a headshot, then a matching driver cutout cropped to the upper square. Car side views keep their transparent background and natural aspect ratio. Ambiguous or failed matches use the built-in placeholder rather than another team's image.

Known 2026 matches use their pinned upstream commit until a changed manifest record is found. New matches load from the live collection. A 2027 forecast requests the 2027 collection; an unpublished collection produces placeholders rather than old-season clothing. One manifest request is shared across an accepted forecast roster, and an older roster response cannot replace a newer one.

Venue and hero photographs use raw GitHub links to the existing processed files in this project's public media directory. Local copies and their attribution records remain available as source assets, but rendered photographs no longer load from the deployed site's media directory. GitHub availability and the source files' download sizes therefore affect image loading. Maps and interface icons drawn as inline SVG remain part of the page.

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

Replacing `web/public/media/ID.webp` alone no longer changes the displayed portrait: the browser uses its upstream repository URL. Keep a local derivative only when needed as a source or attribution record. Do not relabel a different person or car under an existing ID, and preserve transparency where the source has it.

## Circuit images

Current sector maps are transparent SVG surfaces derived from the credited official maps in `web/src/track-guides.json`. Labels and backgrounds are omitted from the compact view, while the full source remains linked. Other circuit outlines use the MIT-licensed `bacinger/f1-circuits` coordinates.

The existing local source files can regenerate `web/src/sector-maps.json` with:

```sh
python -m f1fantasy.circuit_maps
```

Venue photographs live at `web/public/media/CIRCUIT-ID.webp`. Update their Commons attribution records whenever a file changes.
