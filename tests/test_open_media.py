"""Targeted image overrides must retain credits and reject unsuitable licences."""

import importlib.util
import io
import json
from pathlib import Path
import sys

from PIL import Image
import pytest


@pytest.mark.parametrize("licence", ["CC BY-SA 4.0", "CC BY-NC 4.0"])
def test_targeted_override_crop_and_licence_boundary(tmp_path, monkeypatch, licence):
    spec = importlib.util.spec_from_file_location(
        "open_media", Path(__file__).parents[1] / "scripts/fetch_open_media.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "web"
    (root / "public").mkdir(parents=True)
    (root / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (root / "public/forecast.json").write_text(
        json.dumps(
            {"assets": [{"id": "117", "name": "Lewis Hamilton", "kind": "DRIVER"}]}
        )
    )
    original = json.dumps({"other": {"path": "./media/other.webp"}})
    (root / "src/media.json").write_text(original)
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "__file__", str(tmp_path / "scripts/import.py"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "import.py",
            "--asset",
            "117",
            "--file",
            "File:Chosen portrait.jpg",
            "--crop",
            "0,0,100,80",
        ],
    )
    image = io.BytesIO()
    Image.new("RGB", (20, 10), "red").save(image, format="PNG")

    def get(url, **params):
        if url == "https://commons.wikimedia.org/w/api.php":
            assert params["titles"] == "File:Chosen portrait.jpg"
            metadata = {
                "LicenseShortName": {"value": licence},
                "LicenseUrl": {
                    "value": "https://creativecommons.org/licenses/by-sa/4.0/"
                },
                "Artist": {"value": "Example photographer"},
            }
            return type(
                "Response",
                (),
                {
                    "json": lambda self: {
                        "query": {
                            "pages": {
                                "1": {
                                    "title": "File:Chosen portrait.jpg",
                                    "imageinfo": [
                                        {
                                            "url": "https://example.test/photo.png",
                                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Chosen_portrait.jpg",
                                            "extmetadata": metadata,
                                        }
                                    ],
                                }
                            }
                        }
                    }
                },
            )()
        assert url == "https://example.test/photo.png", (
            "Explicit files need no Wikipedia lookup"
        )
        return type("Response", (), {"content": image.getvalue()})()

    monkeypatch.setattr(module, "get", get)
    if "-NC" in licence:
        with pytest.raises(SystemExit, match="No verified open-licensed"):
            module.main()
        assert (root / "src/media.json").read_text() == original
        assert not (root / "public/media/117.webp").exists()
        assert not (tmp_path / "scripts/media-overrides.json").exists()
    else:
        module.main()
        result = json.loads((root / "src/media.json").read_text())
        assert result["other"] == {"path": "./media/other.webp"}
        assert result["117"]["author"] == "Example photographer"
        assert result["117"]["license"] == licence
        assert "Cropped" in result["117"]["changes"]
        assert Image.open(root / "public/media/117.webp").size == (20, 8)
        assert (
            json.loads((root / "public/media/ATTRIBUTION.json").read_text()) == result
        )
        assert (
            json.loads((tmp_path / "scripts/media-overrides.json").read_text())["117"][
                "file"
            ]
            == "File:Chosen portrait.jpg"
        )
