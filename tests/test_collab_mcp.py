"""Tests for the collaboration MCP server."""

import json
import shutil
from pathlib import Path

import pytest

# Point COLLAB_ROOT to a temp directory before importing
import collab_mcp_server as srv


@pytest.fixture(autouse=True)
def tmp_collab(tmp_path, monkeypatch):
    """Redirect COLLAB_ROOT to a temp directory for every test."""
    monkeypatch.setattr(srv, "COLLAB_ROOT", tmp_path / ".collab")
    return tmp_path / ".collab"


# ------------------------------------------------------------------
# collab_write
# ------------------------------------------------------------------


def test_collab_write_creates_directories(tmp_collab):
    """Writing to a channel auto-creates the path."""
    assert not tmp_collab.exists()
    result = srv.collab_write(
        channel="specs",
        filename="test-spec.md",
        content="# Test Spec\n\nHello world.",
    )
    assert "Wrote" in result
    assert (tmp_collab / "specs").is_dir()
    assert (tmp_collab / "specs" / f"{srv._today()}-test-spec.md").exists()


def test_collab_write_frontmatter(tmp_collab):
    """Markdown files get proper YAML frontmatter."""
    srv.collab_write(
        channel="specs",
        filename="test-fm.md",
        content="Body content here.",
        author="architect",
        tags=["liarsdice", "engine"],
        priority="urgent",
    )
    path = tmp_collab / "specs" / f"{srv._today()}-test-fm.md"
    text = path.read_text()

    assert text.startswith("---\n")
    assert "author: architect" in text
    assert "tags: [liarsdice, engine]" in text
    assert "priority: urgent" in text
    assert "Body content here." in text


def test_collab_write_decisions_go_to_open(tmp_collab):
    """Decisions default to the open/ subdirectory."""
    srv.collab_write(
        channel="decisions",
        filename="001-test-decision.md",
        content="Should we do X?",
    )
    assert (tmp_collab / "decisions" / "open" / "001-test-decision.md").exists()


def test_collab_write_inbox_requires_recipient(tmp_collab):
    result = srv.collab_write(
        channel="inbox", filename="ignored", content="hello"
    )
    assert "Error" in result
    assert "recipient" in result


def test_collab_write_unknown_channel():
    result = srv.collab_write(channel="bogus", filename="x", content="y")
    assert "Error" in result
    assert "unknown channel" in result


# ------------------------------------------------------------------
# collab_read
# ------------------------------------------------------------------


def test_collab_read_listing(tmp_collab):
    """Reading a channel without filename returns sorted listing."""
    srv._ensure_dirs()
    (tmp_collab / "specs" / "aaa.md").write_text("---\n---\n\n# First")
    (tmp_collab / "specs" / "bbb.md").write_text("---\n---\n\n# Second")

    result = srv.collab_read(channel="specs")
    assert "aaa.md" in result
    assert "bbb.md" in result
    assert "Channel 'specs':" in result


def test_collab_read_specific_file(tmp_collab):
    srv._ensure_dirs()
    (tmp_collab / "specs" / "myfile.md").write_text("hello world")
    result = srv.collab_read(channel="specs", filename="myfile.md")
    assert result == "hello world"


def test_collab_read_not_found(tmp_collab):
    srv._ensure_dirs()
    result = srv.collab_read(channel="specs", filename="nope.md")
    assert "Not found" in result


def test_collab_read_decisions_checks_both(tmp_collab):
    """Reading decisions checks both open and resolved."""
    srv._ensure_dirs()
    (tmp_collab / "decisions" / "resolved" / "001-test.md").write_text("resolved content")
    result = srv.collab_read(channel="decisions", filename="001-test.md")
    assert "resolved content" in result
    assert "[decisions/resolved]" in result


def test_collab_read_empty_channel(tmp_collab):
    srv._ensure_dirs()
    result = srv.collab_read(channel="analysis")
    assert "empty" in result.lower()


# ------------------------------------------------------------------
# collab_status
# ------------------------------------------------------------------


def test_collab_status_updates_current(tmp_collab):
    """Status writes overwrite current.json."""
    srv.collab_status(state="building", summary="Working on X")
    path = tmp_collab / "status" / "current.json"
    assert path.exists()

    data = json.loads(path.read_text())
    assert data["state"] == "building"
    assert data["summary"] == "Working on X"
    assert "started" in data
    assert "updated" in data


def test_collab_status_appends_log(tmp_collab):
    """Status writes append to log.jsonl."""
    srv.collab_status(state="building", summary="First")
    srv.collab_status(state="testing", summary="Second")

    log_path = tmp_collab / "status" / "log.jsonl"
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["state"] == "building"
    second = json.loads(lines[1])
    assert second["state"] == "testing"


def test_collab_status_preserves_started(tmp_collab):
    """Same state preserves the original started timestamp."""
    srv.collab_status(state="building", summary="Step 1")
    data1 = json.loads((tmp_collab / "status" / "current.json").read_text())

    srv.collab_status(state="building", summary="Step 2")
    data2 = json.loads((tmp_collab / "status" / "current.json").read_text())

    assert data2["started"] == data1["started"]
    assert data2["summary"] == "Step 2"


def test_collab_status_invalid_state(tmp_collab):
    result = srv.collab_status(state="partying", summary="nope")
    assert "Error" in result


# ------------------------------------------------------------------
# collab_decide
# ------------------------------------------------------------------


def test_collab_decide_post_and_resolve(tmp_collab):
    """Full lifecycle: post → resolve moves file and appends resolution."""
    # Post
    result = srv.collab_decide(
        action="post",
        id="001-scoring-model",
        content="How should we score this?",
    )
    assert "posted" in result
    assert (tmp_collab / "decisions" / "open" / "001-scoring-model.md").exists()

    # Resolve
    result = srv.collab_decide(
        action="resolve",
        id="001-scoring-model",
        content="Use elimination scoring.",
        decided_by="dave",
    )
    assert "resolved" in result
    assert not (tmp_collab / "decisions" / "open" / "001-scoring-model.md").exists()

    resolved = tmp_collab / "decisions" / "resolved" / "001-scoring-model.md"
    assert resolved.exists()
    text = resolved.read_text()
    assert "## Resolution" in text
    assert "dave" in text
    assert "Use elimination scoring." in text


def test_collab_decide_resolve_requires_decided_by(tmp_collab):
    srv.collab_decide(action="post", id="002-test", content="Question?")
    result = srv.collab_decide(action="resolve", id="002-test", content="Answer.")
    assert "Error" in result
    assert "decided_by" in result


def test_collab_decide_resolve_not_found(tmp_collab):
    result = srv.collab_decide(
        action="resolve", id="999-nope", content="x", decided_by="dave"
    )
    assert "Not found" in result


# ------------------------------------------------------------------
# collab_inbox
# ------------------------------------------------------------------


def test_collab_inbox_routing(tmp_collab):
    """Messages route to correct recipient folder."""
    srv.collab_inbox(to="architect", message="Check the new engine")
    srv.collab_inbox(to="code", message="Spec ready for review")

    assert (tmp_collab / "inbox" / "to-architect" / "001.json").exists()
    assert (tmp_collab / "inbox" / "to-code" / "001.json").exists()

    arch_msg = json.loads(
        (tmp_collab / "inbox" / "to-architect" / "001.json").read_text()
    )
    assert arch_msg["message"] == "Check the new engine"
    assert arch_msg["to"] == "architect"


def test_collab_inbox_numbering(tmp_collab):
    """Auto-incrementing message numbers."""
    srv.collab_inbox(to="code", message="First")
    srv.collab_inbox(to="code", message="Second")
    srv.collab_inbox(to="code", message="Third")

    folder = tmp_collab / "inbox" / "to-code"
    assert (folder / "001.json").exists()
    assert (folder / "002.json").exists()
    assert (folder / "003.json").exists()


def test_collab_inbox_with_context(tmp_collab):
    srv.collab_inbox(
        to="architect",
        message="Match results ready",
        context={"match_id": "liarsdice-abc123", "path": "output/telemetry/abc.jsonl"},
    )
    doc = json.loads(
        (tmp_collab / "inbox" / "to-architect" / "001.json").read_text()
    )
    assert doc["context"]["match_id"] == "liarsdice-abc123"


def test_collab_inbox_invalid_recipient(tmp_collab):
    result = srv.collab_inbox(to="dave", message="hi")
    assert "Error" in result


# ------------------------------------------------------------------
# Idempotent init
# ------------------------------------------------------------------


def test_idempotent_init(tmp_collab):
    """Running _ensure_dirs twice doesn't break anything."""
    srv._ensure_dirs()
    # Write some state
    (tmp_collab / "specs" / "keep-me.md").write_text("important")
    srv._ensure_dirs()
    assert (tmp_collab / "specs" / "keep-me.md").read_text() == "important"
