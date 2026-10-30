"""Extract clean, transparent sector paths from the credited official track maps."""

import argparse
import json
from pathlib import Path

import contourpy
import numpy as np
from matplotlib.colors import rgb_to_hsv
from PIL import Image
from PIL import ImageDraw
from scipy import ndimage
from scipy.spatial import cKDTree


def simplify(points, tolerance=0.7):
    if len(points) < 3:
        return points
    direction = points[-1] - points[0]
    length = np.linalg.norm(direction)
    if length:
        relative = points - points[0]
        distances = (
            np.abs(relative[:, 0] * direction[1] - relative[:, 1] * direction[0])
            / length
        )
    else:
        distances = np.linalg.norm(points - points[0], axis=1)
    index = int(distances.argmax())
    if distances[index] <= tolerance:
        return points[[0, -1]]
    return np.concatenate(
        (simplify(points[: index + 1])[:-1], simplify(points[index:]))
    )


def extract(path, colors):
    pixels = np.asarray(Image.open(path).convert("RGB"), dtype=float)
    hues = rgb_to_hsv(pixels / 255)[:, :, 0]
    sectors = []
    for color in colors:
        rgb = np.array([int(color[i : i + 2], 16) for i in (1, 3, 5)])
        mask = np.linalg.norm(pixels - rgb, axis=2) < 85
        hue_difference = np.abs(hues - rgb_to_hsv(rgb / 255)[0])
        mask &= np.minimum(hue_difference, 1 - hue_difference) < 0.035
        thickness = ndimage.distance_transform_edt(mask)
        components, count = ndimage.label(mask)
        sizes = np.bincount(components.ravel())
        sizes[0] = 0
        if not count or sizes.max() < 200:
            raise ValueError(f"No continuous sector in {path}: {color}")
        # White sector labels interrupt the coloured track. Retain thin road
        # fragments, discard filled legend boxes, and bridge their label gaps.
        roads = []
        for index in range(1, count + 1):
            if sizes[index] < 200:
                continue
            points = np.argwhere(components == index)
            if np.quantile(thickness[points[:, 0], points[:, 1]], 0.95) <= 6.5:
                roads.append(points)
        if not roads:
            raise ValueError(f"No sector road fragments in {path}: {color}")
        surface = np.zeros(mask.shape, dtype=np.uint8)
        for points in roads:
            surface[points[:, 0], points[:, 1]] = 255
        canvas = Image.fromarray(surface)
        pen = ImageDraw.Draw(canvas)
        connected = roads.pop(0)
        while roads:
            tree = cKDTree(connected)
            candidates = []
            for i, points in enumerate(roads):
                distances, indices = tree.query(points)
                nearest = int(distances.argmin())
                candidates.append((distances[nearest], i, nearest, indices[nearest]))
            distance, index, end, start = min(candidates)
            if distance > 120:
                raise ValueError(f"Unresolved sector gap in {path}: {color}")
            points = roads.pop(index)
            pen.line(
                [tuple(connected[start][::-1]), tuple(points[end][::-1])],
                fill=255,
                width=5,
            )
            connected = np.concatenate((connected, points))
        surface = np.asarray(canvas) > 0
        paths = contourpy.contour_generator(z=surface.astype(float)).lines(0.5)
        sectors.append([simplify(points) for points in paths if len(points) > 8])
    points = np.concatenate([p for sector in sectors for p in sector])
    low, high = points.min(axis=0), points.max(axis=0)
    scale = min(590 / (high[0] - low[0]), 240 / (high[1] - low[1]))
    offset = np.array([45, 30]) + (np.array([590, 240]) - (high - low) * scale) / 2
    return [
        [np.round((p - low) * scale + offset, 2).tolist() for p in sector]
        for sector in sectors
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("web"))
    args = parser.parse_args(argv)
    guides = json.loads((args.root / "src/track-guides.json").read_text())
    maps = {}
    for key, guide in guides.items():
        maps[key] = {
            "season": guide["season"],
            "source": guide["source"],
            "map_source": guide["map_asset"],
            "sectors": extract(
                args.root / "public" / guide["map"], guide["sector_colors"]
            ),
        }
    output = args.root / "src/sector-maps.json"
    output.write_text(json.dumps(maps, allow_nan=False, separators=(",", ":")) + "\n")
    print(f"Published {len(maps)} official sector maps to {output}")


if __name__ == "__main__":
    main()
