#!/usr/bin/env python3
"""One-off: consolidate fragmented projects into their logical roots.

Before the hook resolved cwd→git-root, every subdirectory the user cd'd into
(``backend``, ``frontend/src``, ``locales`` …) and every Claude Code subagent
worktree (``…/.claude/worktrees/agent-XXXX``) became its own piLoci project.
This collapses those fragments back into one project per real repo / scoped app,
re-pointing all data (raw_sessions, raw_analyses, api_tokens, LanceDB memories +
instincts) and re-stamping the survivor's name/slug/cwd.

Dry-run by default. Pass --execute to apply (back up the DB + LanceDB first;
stop the piloci container so SQLite has a single writer).

Usage:
    python scripts/migrate_consolidate_projects.py            # dry-run
    python scripts/migrate_consolidate_projects.py --execute
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path.home() / "app/piloci/data/piloci/piloci.db"
LANCE = Path.home() / "app/piloci/data/piloci/lancedb"

# Canonical roots: a project's cwd is routed to one of these. The survivor is
# the existing project whose cwd == the root path (looked up at runtime).
PILOCI_ROOT = "/home/pi/app/jupyterLab/notebooks/piloci"
MIYOO_ROOT = "/home/pi/app/jupyterLab/notebooks/miyoo-expedition"
MFA_ROOT = "/home/pi/app/jupyterLab/notebooks/mfa-servicenow-mcp"
SORIN_ROOT = "/Users/jshsakura/Documents/workspace/sorin"
# ServiceNow scoped app — not a git repo, so we pick the busiest checkout as the
# survivor and fold dev/test/prod + every artifact dir under it.
XYERGB_ROOT = "/Users/jshsakura/Documents/workspace/sorin/temp/yokogawabpmdev/x_yergb_bpm"

# Nice display names for survivors, keyed by root path.
NAMES = {
    PILOCI_ROOT: ("piLoci", "piloci"),
    MIYOO_ROOT: ("miyoo-expedition", "miyoo-expedition"),
    MFA_ROOT: ("mfa-servicenow-mcp", "mfa-servicenow-mcp"),
    SORIN_ROOT: ("sorin", "sorin"),
    XYERGB_ROOT: ("x_yergb_bpm", "x-yergb-bpm"),
}

# cwd-only projects to drop entirely (accidental ingests, no real project).
JUNK_CWDS = {
    "/tmp",
    "/home/pi/.local/share/fonts/MesloLGS",
    "/home/pi/app/jupyterLab/notebooks",  # parent dir of the real repos
}


def route(cwd: str | None) -> str | None:
    """Return the canonical root path for a cwd, or None to keep standalone."""
    if not cwd:
        return None
    n = cwd.replace("\\", "/").rstrip("/")
    if n in JUNK_CWDS:
        return "__DELETE__"
    # piloci family: repo, /web, agent worktrees, and the deploy checkout.
    if n == "/home/pi/app/piloci" or n.startswith(PILOCI_ROOT):
        return PILOCI_ROOT
    if n.startswith(MIYOO_ROOT):
        return MIYOO_ROOT
    if n.startswith(MFA_ROOT):
        return MFA_ROOT
    # ServiceNow x_yergb_bpm scoped app: every env + artifact dir under sorin/temp.
    if "/x_yergb_bpm" in n or n.split("/")[-1] in (
        "yokogawabpm",
        "yokogawabpmdev",
        "yokogawabpmtest",
    ):
        return XYERGB_ROOT
    if n.startswith(SORIN_ROOT + "/temp"):
        return XYERGB_ROOT
    # Any other sorin subdir (workspace, docs, …) folds into the sorin project.
    if n.startswith(SORIN_ROOT + "/"):
        return SORIN_ROOT
    return None


def main() -> int:
    execute = "--execute" in sys.argv
    con = sqlite3.connect(str(DB))
    projects = con.execute("select id, name, slug, cwd from projects").fetchall()
    by_cwd = {(c or "").replace("\\", "/").rstrip("/"): pid for pid, _, _, c in projects}

    # Build merge plan: absorbed_id -> survivor_id  (and a delete set).
    merges: dict[str, str] = {}
    deletes: set[str] = set()
    survivors: set[str] = set()
    for pid, name, _slug, cwd in projects:
        target_root = route(cwd)
        if target_root is None:
            continue
        if target_root == "__DELETE__":
            deletes.add(pid)
            continue
        survivor = by_cwd.get(target_root)
        if survivor is None:
            print(f"  ! no survivor project found for root {target_root} (skipping {name})")
            continue
        survivors.add(survivor)
        if pid != survivor:
            merges[pid] = survivor

    pname = {pid: (name, slug, cwd) for pid, name, slug, cwd in projects}

    # Counts for the report.
    def sess_count(pid: str) -> int:
        return con.execute(
            "select count(*) from raw_sessions where project_id=?", (pid,)
        ).fetchone()[0]

    print(f"DB: {DB}")
    print(f"projects: {len(projects)}  merges: {len(merges)}  deletes: {len(deletes)}")
    print("\n=== MERGE PLAN ===")
    groups: dict[str, list[str]] = {}
    for a, s in merges.items():
        groups.setdefault(s, []).append(a)
    for s, absorbed in sorted(groups.items(), key=lambda kv: pname[kv[0]][0].lower()):
        sn = pname[s][0]
        print(f"\n  ◆ {sn}  (survivor {s[:8]}, {sess_count(s)} sessions)")
        for a in sorted(absorbed, key=lambda x: pname[x][0]):
            print(f"      ← {pname[a][0]:30} [{pname[a][1]}]  {sess_count(a)} sess")
    print("\n=== DELETE (junk) ===")
    for d in deletes:
        print(f"  ✗ {pname[d][0]:30} {pname[d][2]}  {sess_count(d)} sess")
    keepers = [pid for pid, *_ in projects if pid not in merges and pid not in deletes]
    print(f"\n=== RESULT: {len(keepers)} projects remain ===")
    for pid in sorted(keepers, key=lambda x: pname[x][0].lower()):
        tag = " (survivor)" if pid in survivors else ""
        print(f"  • {pname[pid][0]}{tag}")

    if not execute:
        print("\n(dry-run — pass --execute to apply)")
        return 0

    print("\n>>> EXECUTING")
    # 1) SQLite re-point. user_profiles has PK (user_id, project_id): drop
    #    absorbed rows that would collide, then re-point the rest.
    for absorbed, survivor in merges.items():
        con.execute(
            "delete from user_profiles where project_id=? and user_id in "
            "(select user_id from user_profiles where project_id=?)",
            (absorbed, survivor),
        )
        for tbl in ("raw_sessions", "raw_analyses", "api_tokens", "user_profiles"):
            con.execute(f"update {tbl} set project_id=? where project_id=?", (survivor, absorbed))
    # 2) Delete junk projects' rows everywhere.
    for d in deletes:
        for tbl in ("raw_sessions", "raw_analyses", "api_tokens", "user_profiles"):
            con.execute(f"delete from {tbl} where project_id=?", (d,))
    # 3) Drop absorbed + junk project rows.
    gone = set(merges) | deletes
    con.executemany("delete from projects where id=?", [(g,) for g in gone])
    # 4) Re-stamp survivors' name/slug/cwd to the clean root.
    root_by_survivor = {by_cwd[r]: r for r in NAMES if r in by_cwd}
    for survivor, root in root_by_survivor.items():
        nm, sg = NAMES[root]
        con.execute(
            "update projects set name=?, slug=?, cwd=? where id=?",
            (nm, sg, root, survivor),
        )
    con.commit()
    con.close()

    # 5) LanceDB: re-point memories + instincts project_id.
    import lancedb

    db = lancedb.connect(str(LANCE))
    for tname in db.table_names():
        tbl = db.open_table(tname)
        if "project_id" not in tbl.schema.names:
            continue
        for absorbed, survivor in merges.items():
            tbl.update(where=f"project_id = '{absorbed}'", values={"project_id": survivor})
        for d in deletes:
            tbl.delete(f"project_id = '{d}'")
    print(">>> DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
