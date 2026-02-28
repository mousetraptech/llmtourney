# Global Collab MCP Server Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Promote the collab MCP server from project-local (llmtourney) to global (all projects), adding a `project` parameter to every tool and a new `collab_where_was_i` ADHD context-resumption tool.

**Architecture:** Move `COLLAB_ROOT` from `__file__/.collab/` to `~/projects/.collab/`. Each project gets a subdirectory mirroring the current channel structure. A `projects.json` registry tracks active projects. All existing tools gain an optional `project` param that routes reads/writes to the correct subdirectory. Global-level operations (no project specified) work for inbox and status overview.

**Tech Stack:** Python stdlib + `mcp` SDK (FastMCP). pytest for tests. No new dependencies.

**Spec:** `.collab/specs/2026-02-28-global-collab.md`

---

### Task 1: Create global directory structure and projects.json

**Files:**
- Create: `~/projects/.collab/projects.json`
- Create: `~/projects/.collab/META.md`

**Step 1: Create the global .collab root and project registry**

```bash
mkdir -p ~/projects/.collab
```

**Step 2: Write projects.json**

Create `~/projects/.collab/projects.json`:
```json
{
  "projects": {
    "llmtourney": {
      "name": "LLM Tourney",
      "path": "~/projects/play-games/llmtourney",
      "description": "AI model tournament system — games, telemetry, spectator",
      "status": "active"
    },
    "productionhub": {
      "name": "Production Hub",
      "path": "~/projects/dmms/productionhub",
      "description": "OSC show control — QLab, Avantis, ChamSys, PTZ, OBS, TouchDesigner",
      "status": "active"
    },
    "dmms": {
      "name": "DMMS Infrastructure",
      "path": "~/projects/dmms",
      "description": "Venue technical infrastructure, MOD operations, booth/closet organization",
      "status": "active"
    }
  }
}
```

**Step 3: Write META.md**

A brief file explaining the directory for anyone who encounters it. One paragraph max.

**Step 4: Commit**

```bash
cd ~/projects/.collab
git init  # This is NOT a git repo — skip this. It's just a directory.
```

No commit — this directory is not in a git repo. Just create the files.

---

### Task 2: Migrate existing llmtourney collab data

**Files:**
- Move: `~/projects/play-games/llmtourney/.collab/*` → `~/projects/.collab/llmtourney/`
- Create symlink: `~/projects/play-games/llmtourney/.collab` → `~/projects/.collab/llmtourney`

**Step 1: Move the data**

```bash
# Move contents (not the dir itself) into global structure
mkdir -p ~/projects/.collab/llmtourney
cp -a ~/projects/play-games/llmtourney/.collab/* ~/projects/.collab/llmtourney/
```

**Step 2: Verify migration**

```bash
diff -rq ~/projects/play-games/llmtourney/.collab ~/projects/.collab/llmtourney
```

Should show no differences (except maybe the symlink we'll create).

**Step 3: Replace old directory with symlink**

```bash
rm -rf ~/projects/play-games/llmtourney/.collab
ln -s ~/projects/.collab/llmtourney ~/projects/play-games/llmtourney/.collab
```

**Step 4: Verify symlink works**

```bash
ls -la ~/projects/play-games/llmtourney/.collab/
# Should list the migrated contents
cat ~/projects/play-games/llmtourney/.collab/status/current.json
# Should work fine
```

---

### Task 3: Refactor server — project-aware COLLAB_ROOT and _ensure_dirs

**Files:**
- Modify: `collab_mcp_server.py` (lines 1-60 — config and helpers)
- Test: `tests/test_collab_mcp.py`

This task restructures the server internals. All subsequent tasks build on this.

**Step 1: Write failing test for project-aware directory creation**

Add to `tests/test_collab_mcp.py`:

```python
def test_ensure_project_dirs(tmp_collab):
    """Creating dirs for a specific project creates nested structure."""
    srv._ensure_dirs(project="llmtourney")
    assert (tmp_collab / "llmtourney" / "specs").is_dir()
    assert (tmp_collab / "llmtourney" / "inbox" / "to-code").is_dir()
    assert (tmp_collab / "llmtourney" / "decisions" / "open").is_dir()
```

**Step 2: Run test to verify it fails**

```bash
cd ~/projects/play-games/llmtourney && python -m pytest tests/test_collab_mcp.py::test_ensure_project_dirs -v
```

Expected: FAIL — `_ensure_dirs() got unexpected keyword argument 'project'`

**Step 3: Write failing test for project registry loading**

```python
def test_load_projects_registry(tmp_collab):
    """Server loads and validates projects.json."""
    registry = {"projects": {"testproj": {"name": "Test", "path": "/tmp", "description": "test", "status": "active"}}}
    (tmp_collab / "projects.json").write_text(json.dumps(registry))
    projects = srv._load_projects()
    assert "testproj" in projects
```

**Step 4: Implement core refactor**

Update `collab_mcp_server.py`:

1. Change `COLLAB_ROOT` to `Path.home() / "projects" / ".collab"`
2. Add `_load_projects()` helper that reads `projects.json`
3. Add `_project_root(project)` helper that returns `COLLAB_ROOT / project` (validates against registry)
4. Modify `_ensure_dirs(project=None)` — if project given, creates dirs under `COLLAB_ROOT / project /`; if None, creates global inbox dirs only

```python
COLLAB_ROOT = Path.home() / "projects" / ".collab"

def _load_projects() -> dict:
    """Load the project registry."""
    reg_path = COLLAB_ROOT / "projects.json"
    if reg_path.exists():
        return json.loads(reg_path.read_text()).get("projects", {})
    return {}

def _project_root(project: str | None) -> Path:
    """Return the root directory for a project, or COLLAB_ROOT for global."""
    if project is None:
        return COLLAB_ROOT
    return COLLAB_ROOT / project

def _ensure_dirs(project: str | None = None) -> None:
    """Create channel directory structure for a project (or global)."""
    root = _project_root(project)
    for d in [
        root / "specs",
        root / "reviews",
        root / "status",
        root / "decisions" / "open",
        root / "decisions" / "resolved",
        root / "analysis",
        root / "inbox" / "to-code",
        root / "inbox" / "to-architect",
    ]:
        d.mkdir(parents=True, exist_ok=True)
```

**Step 5: Update test fixture**

The `tmp_collab` fixture monkeypatches `COLLAB_ROOT`. This stays the same — it already provides an isolated root. All existing tests pass since `_ensure_dirs()` with no args still creates the old structure (now at global level).

**Step 6: Run all tests**

```bash
python -m pytest tests/test_collab_mcp.py -v
```

Expected: ALL PASS (existing tests use global-level paths, new tests pass for project-level).

**Step 7: Commit**

```bash
git add collab_mcp_server.py tests/test_collab_mcp.py
git commit -m "refactor: project-aware COLLAB_ROOT and _ensure_dirs"
```

---

### Task 4: Add project parameter to collab_write and collab_read

**Files:**
- Modify: `collab_mcp_server.py` (collab_write, collab_read, _list_channel, _write_status_file, _write_inbox)
- Test: `tests/test_collab_mcp.py`

**Step 1: Write failing tests**

```python
def test_collab_write_to_project(tmp_collab):
    """Writing with project param creates file under project dir."""
    # Need a registry for the project
    (tmp_collab / "projects.json").write_text(json.dumps({
        "projects": {"testproj": {"name": "Test", "path": "/tmp", "description": "test", "status": "active"}}
    }))
    result = srv.collab_write(project="testproj", channel="specs", filename="test.md", content="# Hello")
    assert "Wrote" in result
    assert (tmp_collab / "testproj" / "specs").is_dir()


def test_collab_read_from_project(tmp_collab):
    """Reading with project param reads from project dir."""
    srv._ensure_dirs(project="testproj")
    (tmp_collab / "testproj" / "specs" / "test.md").write_text("project content")
    result = srv.collab_read(project="testproj", channel="specs", filename="test.md")
    assert result == "project content"


def test_collab_write_without_project_uses_global(tmp_collab):
    """Omitting project writes to global root (backwards compat)."""
    result = srv.collab_write(channel="specs", filename="global.md", content="# Global")
    assert "Wrote" in result
    # File should be at root level, not under any project
    assert any((tmp_collab / "specs").iterdir())
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_collab_mcp.py -k "project" -v
```

**Step 3: Implement project param on collab_write**

Add `project: str | None = None` as first param to `collab_write`. Pass it through to `_ensure_dirs(project)`. Use `_project_root(project)` instead of `COLLAB_ROOT` for path resolution. Same pattern for `_write_status_file` and `_write_inbox`.

Key change pattern — everywhere that currently does `COLLAB_ROOT / channel`, change to `_project_root(project) / channel`.

**Step 4: Implement project param on collab_read**

Same pattern: add `project: str | None = None`, use `_project_root(project)` for paths.

**Step 5: Update _list_channel to accept project**

`_list_channel(channel, filter_, project=None)` — uses `_project_root(project)` instead of `COLLAB_ROOT`.

**Step 6: Run all tests**

```bash
python -m pytest tests/test_collab_mcp.py -v
```

Expected: ALL PASS.

**Step 7: Commit**

```bash
git add collab_mcp_server.py tests/test_collab_mcp.py
git commit -m "feat: add project param to collab_write and collab_read"
```

---

### Task 5: Add project parameter to collab_status, collab_decide, collab_inbox

**Files:**
- Modify: `collab_mcp_server.py` (collab_status, collab_decide, collab_inbox)
- Test: `tests/test_collab_mcp.py`

**Step 1: Write failing tests**

```python
def test_collab_status_with_project(tmp_collab):
    """Status update scoped to a project."""
    srv._ensure_dirs(project="testproj")
    result = srv.collab_status(project="testproj", state="building", summary="Working on tests")
    assert "updated" in result.lower() or "building" in result.lower()
    assert (tmp_collab / "testproj" / "status" / "current.json").exists()


def test_collab_decide_with_project(tmp_collab):
    """Decisions scoped to a project."""
    srv._ensure_dirs(project="testproj")
    result = srv.collab_decide(project="testproj", action="post", id="001-test", content="Question?")
    assert "posted" in result
    assert (tmp_collab / "testproj" / "decisions" / "open" / "001-test.md").exists()


def test_collab_inbox_with_project(tmp_collab):
    """Inbox messages scoped to a project."""
    srv._ensure_dirs(project="testproj")
    result = srv.collab_inbox(project="testproj", to="architect", message="Project-scoped message")
    assert "Sent" in result
    assert (tmp_collab / "testproj" / "inbox" / "to-architect" / "001.json").exists()
```

**Step 2: Implement — same pattern as Task 4**

Add `project: str | None = None` param to each tool. Route through `_project_root(project)`.

For `collab_status`: the spec says project is "required" but for backwards compat and gradual migration, keep it optional. Global status updates are still useful.

For `collab_decide`: same — optional but recommended.

For `collab_inbox`: optional. If omitted, uses global inbox.

**Step 3: Run all tests**

```bash
python -m pytest tests/test_collab_mcp.py -v
```

**Step 4: Commit**

```bash
git add collab_mcp_server.py tests/test_collab_mcp.py
git commit -m "feat: add project param to collab_status, collab_decide, collab_inbox"
```

---

### Task 6: Implement collab_where_was_i tool

**Files:**
- Modify: `collab_mcp_server.py`
- Test: `tests/test_collab_mcp.py`

This is the ADHD context tool — the main new feature.

**Step 1: Write failing tests**

```python
def test_where_was_i_all_projects(tmp_collab):
    """Without project arg, returns summary of all registered projects."""
    # Set up registry
    (tmp_collab / "projects.json").write_text(json.dumps({
        "projects": {
            "proj1": {"name": "Project 1", "path": "/tmp/p1", "description": "First", "status": "active"},
            "proj2": {"name": "Project 2", "path": "/tmp/p2", "description": "Second", "status": "active"},
        }
    }))
    # Write status for proj1
    srv._ensure_dirs(project="proj1")
    (tmp_collab / "proj1" / "status" / "current.json").write_text(json.dumps({
        "state": "building", "summary": "Working on X", "updated": "2026-02-28T04:00:00Z"
    }))
    # proj2 has no status yet

    result = srv.collab_where_was_i()
    assert "proj1" in result or "Project 1" in result
    assert "building" in result.lower() or "Working on X" in result
    assert "proj2" in result or "Project 2" in result


def test_where_was_i_single_project(tmp_collab):
    """With project arg, returns detailed status for that project."""
    (tmp_collab / "projects.json").write_text(json.dumps({
        "projects": {"proj1": {"name": "Project 1", "path": "/tmp/p1", "description": "First", "status": "active"}}
    }))
    srv._ensure_dirs(project="proj1")
    (tmp_collab / "proj1" / "status" / "current.json").write_text(json.dumps({
        "state": "building", "summary": "Working on X", "updated": "2026-02-28T04:00:00Z"
    }))
    # Add an open decision
    (tmp_collab / "proj1" / "decisions" / "open" / "001-test.md").write_text("# Open question")
    # Add an inbox message
    (tmp_collab / "proj1" / "inbox" / "to-code" / "001.json").write_text(json.dumps({"message": "Check this"}))

    result = srv.collab_where_was_i(project="proj1")
    assert "building" in result.lower() or "Working on X" in result
    # Should mention open decisions and unread inbox
    assert "decision" in result.lower() or "1" in result
```

**Step 2: Run tests to verify failure**

```bash
python -m pytest tests/test_collab_mcp.py -k "where_was_i" -v
```

**Step 3: Implement collab_where_was_i**

```python
@mcp.tool()
def collab_where_was_i(project: str | None = None) -> str:
    """The ADHD tool. Shows where you left off across all projects, or details for one.

    Args:
        project: Optional. If omitted, returns summary of all projects.
    """
    projects = _load_projects()
    if not projects:
        return "No projects registered. Create ~/projects/.collab/projects.json first."

    if project:
        # Detailed view for one project
        if project not in projects:
            return f"Unknown project '{project}'. Registered: {', '.join(projects.keys())}"
        return _where_was_i_detail(project, projects[project])

    # Summary of all projects
    lines = ["# Where Was I?\n"]
    for proj_key, proj_info in projects.items():
        root = COLLAB_ROOT / proj_key
        status = _read_project_status(root)
        open_decisions = _count_files(root / "decisions" / "open")
        unread_code = _count_files(root / "inbox" / "to-code")

        state_emoji = {"building": "🔨", "testing": "🧪", "blocked": "🔴", "done": "✅", "reviewing": "👀"}.get(status.get("state", ""), "⚪")

        lines.append(f"## {proj_info['name']} — {state_emoji} {status.get('state', 'no status')}")
        lines.append(status.get("summary", "(no status update yet)"))
        lines.append(f"Open decisions: {open_decisions} | Unread inbox: {unread_code}")
        if status.get("updated"):
            lines.append(f"Last active: {status['updated']}")
        lines.append("")

    return "\n".join(lines)
```

Helper functions:

```python
def _read_project_status(root: Path) -> dict:
    path = root / "status" / "current.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return {}

def _count_files(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(1 for f in directory.iterdir() if not f.name.startswith("."))

def _where_was_i_detail(project: str, info: dict) -> str:
    root = COLLAB_ROOT / project
    status = _read_project_status(root)
    open_decisions = _count_files(root / "decisions" / "open")
    unread_code = _count_files(root / "inbox" / "to-code")

    lines = [f"# {info['name']}\n"]
    lines.append(f"**State:** {status.get('state', 'no status')}")
    lines.append(f"**Summary:** {status.get('summary', '(none)')}")
    if status.get("updated"):
        lines.append(f"**Last active:** {status['updated']}")
    if status.get("blocking"):
        lines.append(f"**Blocked on:** {status['blocking']}")
    if status.get("next_steps"):
        lines.append("\n**Next steps:**")
        for step in status["next_steps"]:
            lines.append(f"- {step}")

    lines.append(f"\n**Open decisions:** {open_decisions}")
    if open_decisions > 0:
        for f in sorted((root / "decisions" / "open").iterdir()):
            if not f.name.startswith("."):
                lines.append(f"  - {f.stem}")

    lines.append(f"**Unread inbox:** {unread_code}")
    if unread_code > 0:
        for f in sorted((root / "inbox" / "to-code").iterdir()):
            if not f.name.startswith("."):
                try:
                    msg = json.loads(f.read_text())
                    prio = f" [{msg.get('priority', 'normal')}]" if msg.get('priority') == 'urgent' else ""
                    lines.append(f"  - {f.name}{prio}: {msg.get('message', '')[:80]}")
                except Exception:
                    lines.append(f"  - {f.name}")

    # Last 3 log entries
    log_path = root / "status" / "log.jsonl"
    if log_path.exists():
        log_lines = log_path.read_text().strip().splitlines()
        recent = log_lines[-3:] if len(log_lines) >= 3 else log_lines
        if recent:
            lines.append("\n**Recent activity:**")
            for entry_line in reversed(recent):
                try:
                    entry = json.loads(entry_line)
                    lines.append(f"  - [{entry.get('state', '?')}] {entry.get('summary', '')} ({entry.get('timestamp', '')})")
                except Exception:
                    pass

    return "\n".join(lines)
```

**Step 4: Run all tests**

```bash
python -m pytest tests/test_collab_mcp.py -v
```

**Step 5: Commit**

```bash
git add collab_mcp_server.py tests/test_collab_mcp.py
git commit -m "feat: add collab_where_was_i ADHD context tool"
```

---

### Task 7: Move server file to global location and re-register

**Files:**
- Move: `~/projects/play-games/llmtourney/collab_mcp_server.py` → `~/projects/.collab/collab_mcp_server.py`
- Move: `~/projects/play-games/llmtourney/tests/test_collab_mcp.py` → `~/projects/.collab/tests/test_collab_mcp.py`

**Step 1: Copy server to global location**

```bash
cp ~/projects/play-games/llmtourney/collab_mcp_server.py ~/projects/.collab/collab_mcp_server.py
cp -r ~/projects/play-games/llmtourney/tests/test_collab_mcp.py ~/projects/.collab/tests/test_collab_mcp.py
```

Actually — wait. The test file imports `collab_mcp_server as srv` from the project root. And the server's `COLLAB_ROOT` is now `Path.home() / "projects" / ".collab"` (not relative to `__file__`). The server file can live anywhere.

Per the spec: "Server lives at the global collab root: `~/projects/.collab/collab_mcp_server.py`"

**Step 1: Move the server file**

```bash
cp ~/projects/play-games/llmtourney/collab_mcp_server.py ~/projects/.collab/collab_mcp_server.py
```

Keep the old one in llmtourney for now (tests reference it). We can remove it after confirming the global one works.

**Step 2: Create test directory at global location**

```bash
mkdir -p ~/projects/.collab/tests
cp ~/projects/play-games/llmtourney/tests/test_collab_mcp.py ~/projects/.collab/tests/test_collab_mcp.py
```

Update import path in the global test copy to reference the server correctly:
```python
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import collab_mcp_server as srv
```

**Step 3: Run tests from global location**

```bash
cd ~/projects/.collab && python -m pytest tests/test_collab_mcp.py -v
```

**Step 4: Re-register MCP server**

```bash
claude mcp remove collab
claude mcp add --scope user collab -- python ~/projects/.collab/collab_mcp_server.py
```

**Step 5: Verify registration**

```bash
claude mcp list
```

Should show collab at user scope pointing to `~/projects/.collab/collab_mcp_server.py`.

**Step 6: Clean up old server from llmtourney**

```bash
rm ~/projects/play-games/llmtourney/collab_mcp_server.py
```

Keep the test in llmtourney's test suite if desired, or remove it. The canonical tests now live at `~/projects/.collab/tests/`.

**Step 7: Commit the llmtourney cleanup**

```bash
cd ~/projects/play-games/llmtourney
git add -A
git commit -m "chore: move collab MCP server to global ~/projects/.collab/"
```

---

### Task 8: Update server instructions and docstring

**Files:**
- Modify: `~/projects/.collab/collab_mcp_server.py` (docstring, FastMCP instructions)

**Step 1: Update docstring and instructions**

Change the FastMCP constructor:
```python
mcp = FastMCP("collab", instructions="Global collaboration workspace across all projects. Use 'project' param to scope operations. Use collab_where_was_i to get context on all projects.")
```

Update module docstring:
```python
"""Global Collaboration MCP server.

Provides a shared workspace at ~/projects/.collab/ for asynchronous
collaboration between Claude Code and Claude.ai across all projects.

Usage:
    claude mcp add --scope user collab -- python ~/projects/.collab/collab_mcp_server.py
"""
```

**Step 2: Verify server starts**

```bash
echo '{"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "0.1"}}, "id": 1}' | python ~/projects/.collab/collab_mcp_server.py 2>/dev/null | head -1
```

Should return a JSON-RPC response (not crash).

---

### Task 9: Write STATUS.md and smoke test

**Files:**
- Create: `~/projects/.collab/STATUS.md`

**Step 1: Generate initial STATUS.md**

After all tools work, use `collab_where_was_i()` output to populate `STATUS.md` with current state of all projects. This can also be done manually:

```markdown
# Global Project Status

Last updated: 2026-02-28

## Active Projects

### LLM Tourney — ✅ done
Re-launched 9-player liarsdice redistribution match
Open decisions: 0 | Unread: 0

### Production Hub — ⚪ no status
(newly registered — no status updates yet)
Open decisions: 0 | Unread: 0

### DMMS Infrastructure — ⚪ no status
(newly registered — no status updates yet)
Open decisions: 0 | Unread: 0
```

**Step 2: Smoke test the full flow**

In a Claude Code session, verify:
1. `collab_where_was_i()` — returns all projects
2. `collab_where_was_i(project="llmtourney")` — returns llmtourney detail
3. `collab_status(project="llmtourney", state="done", summary="Global collab migration complete")` — updates status
4. `collab_inbox(project="llmtourney", to="architect", message="Migration complete")` — sends message
5. `collab_read(project="llmtourney", channel="inbox")` — lists inbox

---

## Summary

| Task | Description | Estimated Changes |
|------|-------------|-------------------|
| 1 | Create global directory + projects.json | New files only |
| 2 | Migrate llmtourney data + symlink | File moves |
| 3 | Refactor server internals (project-aware root) | ~30 lines changed |
| 4 | Add project param to write/read | ~40 lines changed |
| 5 | Add project param to status/decide/inbox | ~20 lines changed |
| 6 | Implement collab_where_was_i | ~80 new lines |
| 7 | Move server to global location, re-register | File moves + MCP config |
| 8 | Update docstrings and instructions | ~10 lines |
| 9 | STATUS.md + smoke test | New file + manual test |

Total: server stays under 400 lines per spec constraint. ~6 commits.
