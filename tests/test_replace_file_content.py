"""Tests for POST /files/replace and the removal of the ADD endpoints.

The insert_after / append_to_section / append endpoints were added on
2026-08-01 against a misdiagnosed failure and never invoked
(dvystrcil/homelab#1150). They are removed; the one change kept is a
more instructive "Target string not found" message, as proposed by the
upstream maintainer on open-webui/open-terminal#151.
"""

import os

from fastapi.testclient import TestClient

from open_terminal.main import app

AUTH = {"Authorization": f"Bearer {os.environ['OPEN_TERMINAL_API_KEY']}"}


def _client():
    return TestClient(app)


def test_replace_still_replaces(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("# Title\n\nold line\n")
    r = _client().post(
        "/files/replace",
        headers=AUTH,
        json={"path": str(f), "replacements": [{"target": "old line", "replacement": "new line"}]},
    )
    assert r.status_code == 200, r.text
    assert f.read_text() == "# Title\n\nnew line\n"


def test_target_not_found_explains_exact_match_and_how_to_add(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("# Title\n\nold line\n")
    r = _client().post(
        "/files/replace",
        headers=AUTH,
        json={"path": str(f), "replacements": [{"target": "missing", "replacement": "x"}]},
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail.startswith("Target string not found: 'missing'")
    assert "exact substring" in detail
    assert "Re-read the file" in detail
    assert "To ADD new content" in detail
    assert f.read_text() == "# Title\n\nold line\n"


def test_target_equal_to_replacement_first_line_is_a_normal_replace(tmp_path):
    # The removed defensive check refused this shape. Anchoring on an
    # existing line and repeating it at the start of the replacement is
    # exactly how the new error message tells a model to ADD content.
    f = tmp_path / "a.md"
    f.write_text("## Section\nbody\n")
    r = _client().post(
        "/files/replace",
        headers=AUTH,
        json={
            "path": str(f),
            "replacements": [{"target": "## Section", "replacement": "## Section\nadded"}],
        },
    )
    assert r.status_code == 200, r.text
    assert f.read_text() == "## Section\nadded\nbody\n"


def test_add_endpoints_are_gone():
    paths = set(app.openapi()["paths"])
    for p in ("/files/insert_after", "/files/append_to_section", "/files/append"):
        assert p not in paths, p
