import numpy as np
import pytest
from PIL import Image, ImageDraw

from f1fantasy.circuit_maps import extract


def test_sector_extraction_retains_track_across_labels_without_legend_boxes(tmp_path):
    image = Image.new("RGB", (1000, 500), "black")
    draw = ImageDraw.Draw(image)
    colors = ["#e6007e", "#f5d526", "#4a9ed8"]
    for y, color in zip((100, 200, 300), colors):
        draw.line([(100, y), (900, y)], fill=color, width=6)
        draw.rectangle((430, y - 10, 500, y + 10), fill="white")
        draw.rectangle((10, 400, 80, 425), fill=color)
    path = tmp_path / "source.png"
    image.save(path)
    sectors = extract(path, colors)
    for sector in sectors:
        points = np.concatenate(sector)
        assert points[:, 0].min() == pytest.approx(45)
        assert points[:, 0].max() == pytest.approx(635)
        assert np.ptp(points[:, 1]) < 10


def test_missing_verified_sector_is_not_replaced_by_an_invented_split(tmp_path):
    path = tmp_path / "blank.png"
    Image.new("RGB", (1000, 500), "black").save(path)
    with pytest.raises(ValueError, match="No continuous sector"):
        extract(path, ["#e6007e"])
