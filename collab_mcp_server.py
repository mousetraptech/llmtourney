#!/usr/bin/env python3
"""Collaboration MCP server for LLM Tourney.

Gives Claude Code and Claude.ai a shared workspace at .collab/ for
asynchronous collaboration. Stdio transport, stdlib + mcp SDK only.

Usage:
    claude mcp add --scope local collab -- python collab_mcp_server.py
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

COLLAB_ROOT = Path(__file__).parent / ".collab"

CHANNELS = ("specs", "reviews", "status", "decisions", "analysis", "inbox")

VALID_STATES = ("building", "testing", "blocked", "done", "reviewing")
VALID_PRIORITIES = ("normal", "urgent")
VALID_AUTHORS = ("code", "architect", "dave")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _ensure_dirs() -> None:
    """Create the full .collab directory structure if missing."""
    for d in [
        COLLAB_ROOT / "specs",
        COLLAB_ROOT / "reviews",
        COLLAB_ROOT / "status",
        COLLAB_ROOT / "decisions" / "open",
        COLLAB_ROOT / "decisions" / "resolved",
        COLLAB_ROOT / "analysis",
        COLLAB_ROOT / "inbox" / "to-code",
        COLLAB_ROOT / "inbox" / "to-architect",
    ]:
        d.mkdir(parents=True, exist_ok=True)


def _build_frontmatter(
    author: str = "code",
    tags: list[str] | None = None,
    status: str = "active",
    priority: str = "normal",
) -> str:
    lines = [
        "---",
        f"author: {author}",
        f"created: {_now_iso()}",
        f"tags: [{', '.join(tags or [])}]",
        f"status: {status}",
        f"priority: {priority}",
        "---",
    ]
    return "\n".join(lines)


def _next_number(directory: Path) -> int:
    """Find the next auto-increment number in a directory."""
    existing = list(directory.iterdir()) if directory.exists() else []
    nums = []
    for f in existing:
        stem = f.stem
        # Extract leading digits
        digits = ""
        for ch in stem:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            nums.append(int(digits))
    return max(nums, default=0) + 1


def _first_line_summary(path: Path, max_len: int = 80) -> str:
    """Extract first non-frontmatter, non-blank line as summary."""
    try:
        in_frontmatter = False
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped == "---":
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                continue
            if stripped and not stripped.startswith("#"):
                return stripped[:max_len]
            if stripped.startswith("#"):
                return stripped[:max_len]
        return "(empty)"
    except Exception:
        return "(unreadable)"


def _list_channel(channel: str, filter_: str | None = None) -> str:
    """List files in a channel with timestamps and summaries."""
    _ensure_dirs()

    if channel == "decisions":
        if filter_ == "resolved":
            target = COLLAB_ROOT / "decisions" / "resolved"
        elif filter_ == "open" or filter_ is None:
            target = COLLAB_ROOT / "decisions" / "open"
        else:
            # List both
            target = None
    elif channel == "inbox":
        # List both subfolders
        target = None
    else:
        target = COLLAB_ROOT / channel

    entries = []

    if target is not None:
        if target.exists():
            for f in sorted(target.iterdir()):
                if f.name.startswith("."):
                    continue
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                summary = _first_line_summary(f) if f.suffix == ".md" else ""
                entries.append(f"  {f.name}  ({mtime:%Y-%m-%d %H:%M})  {summary}")
    else:
        # Multi-folder channels
        if channel == "decisions":
            for sub in ("open", "resolved"):
                subdir = COLLAB_ROOT / "decisions" / sub
                if subdir.exists():
                    for f in sorted(subdir.iterdir()):
                        if f.name.startswith("."):
                            continue
                        mtime = datetime.fromtimestamp(
                            f.stat().st_mtime, tz=timezone.utc
                        )
                        entries.append(
                            f"  [{sub}] {f.name}  ({mtime:%Y-%m-%d %H:%M})  {_first_line_summary(f)}"
                        )
        elif channel == "inbox":
            for sub in ("to-code", "to-architect"):
                subdir = COLLAB_ROOT / "inbox" / sub
                if subdir.exists():
                    for f in sorted(subdir.iterdir()):
                        if f.name.startswith("."):
                            continue
                        mtime = datetime.fromtimestamp(
                            f.stat().st_mtime, tz=timezone.utc
                        )
                        entries.append(f"  [{sub}] {f.name}  ({mtime:%Y-%m-%d %H:%M})")

    if not entries:
        return f"Channel '{channel}' is empty."
    return f"Channel '{channel}':\n" + "\n".join(entries)


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("collab", instructions="LLM Tourney collaboration workspace")


@mcp.tool()
def collab_write(
    channel: str,
    filename: str,
    content: str,
    author: str = "code",
    tags: list[str] | None = None,
    priority: str = "normal",
    recipient: str | None = None,
) -> str:
    """Write a document to a collaboration channel.

    Args:
        channel: One of specs, reviews, status, decisions, analysis, inbox
        filename: Filename (auto-prefixed with date for specs/reviews/analysis)
        content: File content (markdown or JSON)
        author: Who is writing — code, architect, or dave
        tags: Optional tags for frontmatter
        priority: normal or urgent
        recipient: For inbox channel — code or architect
    """
    if channel not in CHANNELS:
        return f"Error: unknown channel '{channel}'. Must be one of: {', '.join(CHANNELS)}"

    _ensure_dirs()

    if channel == "status":
        return _write_status_file(filename, content)

    if channel == "inbox":
        if not recipient:
            return "Error: inbox channel requires 'recipient' (code or architect)"
        return _write_inbox(recipient, content, priority, author)

    if channel == "decisions":
        target_dir = COLLAB_ROOT / "decisions" / "open"
    else:
        target_dir = COLLAB_ROOT / channel

    # Auto-prefix date for specs, reviews, analysis
    if channel in ("specs", "reviews", "analysis"):
        if not filename[:4].isdigit():
            filename = f"{_today()}-{filename}"

    if not filename.endswith(".md"):
        filename += ".md"

    frontmatter = _build_frontmatter(
        author=author, tags=tags, priority=priority
    )
    full_content = frontmatter + "\n\n" + content

    path = target_dir / filename
    path.write_text(full_content)
    return f"Wrote {path.relative_to(COLLAB_ROOT)}"


def _write_status_file(filename: str, content: str) -> str:
    """Handle status channel writes (current.json or log.jsonl)."""
    status_dir = COLLAB_ROOT / "status"
    if filename == "current.json":
        (status_dir / "current.json").write_text(content)
        return "Updated status/current.json"
    elif filename == "log.jsonl":
        with open(status_dir / "log.jsonl", "a") as f:
            f.write(content.rstrip("\n") + "\n")
        return "Appended to status/log.jsonl"
    else:
        (status_dir / filename).write_text(content)
        return f"Wrote status/{filename}"


def _write_inbox(
    recipient: str, message: str, priority: str, author: str
) -> str:
    folder = COLLAB_ROOT / "inbox" / f"to-{recipient}"
    if not folder.exists():
        return f"Error: unknown recipient '{recipient}'"
    num = _next_number(folder)
    filename = f"{num:03d}.json"
    doc = {
        "from": author,
        "to": recipient,
        "timestamp": _now_iso(),
        "priority": priority,
        "message": message,
    }
    (folder / filename).write_text(json.dumps(doc, indent=2) + "\n")
    return f"Sent message to inbox/to-{recipient}/{filename}"


@mcp.tool()
def collab_read(
    channel: str,
    filename: str | None = None,
    filter: str | None = None,
) -> str:
    """Read a document or list a channel.

    Args:
        channel: Which channel to read from
        filename: Specific file (if omitted, lists the channel)
        filter: Optional — latest, unread, open, resolved
    """
    if channel not in CHANNELS:
        return f"Error: unknown channel '{channel}'. Must be one of: {', '.join(CHANNELS)}"

    _ensure_dirs()

    if filename is None:
        return _list_channel(channel, filter)

    # Find the file
    if channel == "decisions":
        # Check both open and resolved
        for sub in ("open", "resolved"):
            path = COLLAB_ROOT / "decisions" / sub / filename
            if path.exists():
                return f"[decisions/{sub}]\n\n{path.read_text()}"
        return f"Not found: decisions/{{open,resolved}}/{filename}"
    elif channel == "inbox":
        # Check both subfolders
        for sub in ("to-code", "to-architect"):
            path = COLLAB_ROOT / "inbox" / sub / filename
            if path.exists():
                return f"[inbox/{sub}]\n\n{path.read_text()}"
        return f"Not found: inbox/{{to-code,to-architect}}/{filename}"
    else:
        path = COLLAB_ROOT / channel / filename
        if path.exists():
            return path.read_text()
        return f"Not found: {channel}/{filename}"


@mcp.tool()
def collab_status(
    state: str,
    summary: str,
    details: str | None = None,
    files_touched: list[str] | None = None,
    blocking: str | None = None,
) -> str:
    """Quick status update — writes current.json and appends to log.jsonl.

    Args:
        state: building, testing, blocked, done, or reviewing
        summary: One-line description of current work
        details: Optional longer context
        files_touched: Optional list of file paths being modified
        blocking: Optional description of what's blocking progress
    """
    if state not in VALID_STATES:
        return f"Error: state must be one of: {', '.join(VALID_STATES)}"

    _ensure_dirs()
    now = _now_iso()
    status_dir = COLLAB_ROOT / "status"

    # Read existing to preserve 'started' timestamp
    current_path = status_dir / "current.json"
    started = now
    if current_path.exists():
        try:
            prev = json.loads(current_path.read_text())
            if prev.get("state") == state:
                started = prev.get("started", now)
        except (json.JSONDecodeError, KeyError):
            pass

    current = {
        "state": state,
        "summary": summary,
        "started": started,
        "updated": now,
        "files_touched": files_touched or [],
        "blocking": blocking,
    }
    current_path.write_text(json.dumps(current, indent=2) + "\n")

    # Append to log
    log_entry = {"timestamp": now, "state": state, "summary": summary}
    if details:
        log_entry["details"] = details
    with open(status_dir / "log.jsonl", "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    return f"Status updated: [{state}] {summary}"


@mcp.tool()
def collab_decide(
    action: str,
    id: str,
    content: str,
    decided_by: str | None = None,
) -> str:
    """Post or resolve a decision.

    Args:
        action: post or resolve
        id: Decision ID (e.g. 001-scoring-model)
        content: For post — the question. For resolve — the decision and rationale.
        decided_by: For resolve — dave, architect, or code
    """
    if action not in ("post", "resolve"):
        return "Error: action must be 'post' or 'resolve'"

    _ensure_dirs()

    filename = id if id.endswith(".md") else f"{id}.md"

    if action == "post":
        path = COLLAB_ROOT / "decisions" / "open" / filename
        frontmatter = _build_frontmatter(author="code", status="draft", priority="normal")
        path.write_text(frontmatter + "\n\n" + content)
        return f"Decision posted: decisions/open/{filename}"

    # resolve
    if not decided_by:
        return "Error: 'decided_by' required for resolve action"

    open_path = COLLAB_ROOT / "decisions" / "open" / filename
    resolved_path = COLLAB_ROOT / "decisions" / "resolved" / filename

    if open_path.exists():
        existing = open_path.read_text()
        resolution = (
            f"\n\n---\n\n## Resolution\n\n"
            f"**Decided by:** {decided_by}  \n"
            f"**Date:** {_now_iso()}\n\n"
            f"{content}"
        )
        resolved_path.write_text(existing + resolution)
        open_path.unlink()
        return f"Decision resolved: decisions/resolved/{filename}"
    elif resolved_path.exists():
        return f"Already resolved: decisions/resolved/{filename}"
    else:
        return f"Not found: decisions/open/{filename}"


@mcp.tool()
def collab_inbox(
    to: str,
    message: str,
    priority: str = "normal",
    context: dict | None = None,
) -> str:
    """Send a quick message to code or architect.

    Args:
        to: Recipient — code or architect
        message: The message
        priority: normal or urgent
        context: Optional structured context (file paths, match IDs, etc.)
    """
    if to not in ("code", "architect"):
        return "Error: 'to' must be 'code' or 'architect'"
    if priority not in VALID_PRIORITIES:
        return f"Error: priority must be one of: {', '.join(VALID_PRIORITIES)}"

    _ensure_dirs()
    folder = COLLAB_ROOT / "inbox" / f"to-{to}"
    num = _next_number(folder)
    filename = f"{num:03d}.json"
    doc = {
        "from": "code",
        "to": to,
        "timestamp": _now_iso(),
        "priority": priority,
        "message": message,
    }
    if context:
        doc["context"] = context
    (folder / filename).write_text(json.dumps(doc, indent=2) + "\n")
    return f"Sent message: inbox/to-{to}/{filename}"


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _ensure_dirs()
    mcp.run(transport="stdio")
