"""Static demo mode and safe build-output ownership regressions."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_site import BUILD_MARKER, build, transform_dashboard

ROOT = Path(__file__).resolve().parents[1]


def test_static_build_enables_demo_without_failed_api_requests(tmp_path):
    out = tmp_path / "site"
    build(str(out), str(ROOT))
    html = (out / "index.html").read_text(encoding="utf-8")
    assert '<body data-mode="demo" data-demo-only="true">' in html
    assert 'data-mode="real"' not in html
    assert json.loads((out / BUILD_MARKER).read_text(encoding="utf-8"))["path"] == str(out.resolve())


def test_transform_updates_existing_mode_and_preserves_body_attributes():
    html = transform_dashboard('<body class="dashboard" data-mode="real"><main></main></body>')
    assert '<body class="dashboard" data-mode="demo" data-demo-only="true">' in html


def test_build_refuses_unowned_directory_without_touching_files(tmp_path):
    out = tmp_path / "personal"
    out.mkdir()
    sentinel = out / "notes.txt"
    sentinel.write_text("must survive", encoding="utf-8")
    with pytest.raises(ValueError, match="构建标记"):
        build(str(out), str(ROOT))
    assert sentinel.read_text(encoding="utf-8") == "must survive"
    assert not (out / "index.html").exists()


def test_repeat_build_preserves_unrelated_files(tmp_path):
    out = tmp_path / "site"
    build(str(out), str(ROOT))
    sentinel = out / "notes.txt"
    sentinel.write_text("must survive", encoding="utf-8")
    build(str(out), str(ROOT))
    assert sentinel.read_text(encoding="utf-8") == "must survive"


@pytest.mark.parametrize("relative", [".", "web", "web/nested", "scripts", "emotion", ".git"])
def test_build_refuses_project_and_source_paths(relative):
    with pytest.raises(ValueError, match="输出目录"):
        build(str(ROOT / relative), str(ROOT))


def test_build_refuses_project_parent():
    with pytest.raises(ValueError, match="父目录"):
        build(str(ROOT.parent), str(ROOT))


def test_build_refuses_invalid_marker_without_touching_files(tmp_path):
    out = tmp_path / "site"
    out.mkdir()
    (out / BUILD_MARKER).write_text('{"kind":"unrelated"}', encoding="utf-8")
    with pytest.raises(ValueError, match="不匹配"):
        build(str(out), str(ROOT))
    assert not (out / "index.html").exists()


def test_build_refuses_asset_symlink(tmp_path):
    out = tmp_path / "site"
    build(str(out), str(ROOT))
    target = tmp_path / "private.txt"
    target.write_text("must survive", encoding="utf-8")
    asset = out / "static" / "app.js"
    asset.unlink()
    try:
        asset.symlink_to(target)
    except OSError:
        pytest.skip("Creating symlinks requires host privileges")
    with pytest.raises(ValueError, match="符号链接"):
        build(str(out), str(ROOT))
    assert target.read_text(encoding="utf-8") == "must survive"
