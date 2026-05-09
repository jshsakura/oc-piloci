from __future__ import annotations

"""Backfill ``Project.cwd`` from raw_session transcripts and split misattributed
sessions.

Used to recover from the pre-v0.2.66 slug-collision bug where two folders that
slugify the same merged into one project. Memories don't carry a session
backlink so they stay where they are; only ``raw_sessions`` are reassigned.

The flow:
1. Walk every project whose ``cwd`` is NULL (legacy rows).
2. For each session under that project, parse the transcript and pick the most
   common ``cwd`` field as that session's source directory.
3. Group sessions by detected cwd. The majority cwd becomes the project's
   canonical cwd (stamped onto the existing row).
4. Each minority cwd group is split off into its own project — slug derived
   from the folder name, disambiguated with a 6-char hash on collision. The
   matching raw_sessions are reassigned.

Idempotent: projects that already have ``cwd`` set are skipped. Safe to run
repeatedly; ``--dry-run`` produces the same report without mutating anything.
"""

import hashlib
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import orjson
from sqlalchemy import select, update

from piloci.db.models import Project, RawSession
from piloci.db.session import async_session

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """ASCII-safe slug — mirrors ``memory_tools._slugify`` to avoid an import cycle."""
    import re

    ascii_only = text.encode("ascii", errors="ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug[:40] or "project"


def _dir_name(cwd: str) -> str:
    normalized = cwd.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] or "project"


def _disambig_slug(base_slug: str, cwd: str) -> str:
    suffix = hashlib.sha1(cwd.encode("utf-8")).hexdigest()[:6]
    return f"{base_slug}-{suffix}"[:50]


def _extract_session_cwd(transcript_json: str) -> str | None:
    """Return the dominant ``cwd`` seen in the transcript entries, or None."""
    try:
        entries = orjson.loads(transcript_json)
    except orjson.JSONDecodeError:
        return None
    if not isinstance(entries, list):
        return None
    counts: Counter[str] = Counter()
    for entry in entries:
        if isinstance(entry, dict):
            cwd = entry.get("cwd")
            if isinstance(cwd, str) and cwd:
                counts[cwd] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


async def backfill_cwd(*, dry_run: bool = False, user_id: str | None = None) -> dict[str, Any]:
    """Walk legacy projects and split misattributed sessions by transcript cwd.

    Parameters
    ----------
    dry_run:
        If True, return the planned actions without writing.
    user_id:
        Restrict the run to a single user when set.

    Returns a report dict summarizing what changed.
    """

    report: dict[str, Any] = {
        "dry_run": dry_run,
        "projects_examined": 0,
        "projects_stamped": 0,
        "projects_split": 0,
        "sessions_moved": 0,
        "new_projects": 0,
        "details": [],
    }

    async with async_session() as db:
        q = select(Project).where(Project.cwd.is_(None))
        if user_id:
            q = q.where(Project.user_id == user_id)
        projects = (await db.execute(q)).scalars().all()
        # Detach from session so we can iterate without an open transaction.
        project_rows = [(p.id, p.user_id, p.slug, p.name) for p in projects]

    for project_id, project_user_id, project_slug, project_name in project_rows:
        report["projects_examined"] += 1

        async with async_session() as db:
            sessions = (
                (
                    await db.execute(
                        select(RawSession).where(
                            RawSession.user_id == project_user_id,
                            RawSession.project_id == project_id,
                        )
                    )
                )
                .scalars()
                .all()
            )

        if not sessions:
            report["details"].append({"project": project_slug, "action": "skip_empty"})
            continue

        # Bucket sessions by detected cwd.
        groups: dict[str | None, list[str]] = {}
        for s in sessions:
            cwd = _extract_session_cwd(s.transcript_json)
            groups.setdefault(cwd, []).append(s.ingest_id)

        detected = {k: v for k, v in groups.items() if k is not None}
        if not detected:
            report["details"].append(
                {"project": project_slug, "action": "skip_no_cwd_in_transcripts"}
            )
            continue

        majority_cwd = max(detected, key=lambda k: len(detected[k]))

        detail: dict[str, Any] = {
            "project": project_slug,
            "majority_cwd": majority_cwd,
            "groups": {(k or "<unknown>"): len(v) for k, v in groups.items()},
            "splits": [],
        }

        # Stamp the project with its real cwd.
        if not dry_run:
            async with async_session() as db:
                live = (
                    await db.execute(select(Project).where(Project.id == project_id))
                ).scalar_one()
                live.cwd = majority_cwd
                await db.commit()
        report["projects_stamped"] += 1

        had_split = False
        for cwd, ingest_ids in groups.items():
            if cwd is None or cwd == majority_cwd:
                continue
            had_split = True

            target_id: str | None = None
            async with async_session() as db:
                # Reuse an existing project that already owns this cwd.
                existing = (
                    await db.execute(
                        select(Project).where(
                            Project.user_id == project_user_id, Project.cwd == cwd
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    target_id = existing.id
                    detail["splits"].append(
                        {
                            "cwd": cwd,
                            "to_slug": existing.slug,
                            "sessions": len(ingest_ids),
                            "reused": True,
                        }
                    )
                else:
                    base_slug = _slugify(_dir_name(cwd))
                    new_slug = base_slug
                    taken = (
                        await db.execute(
                            select(Project.id).where(
                                Project.user_id == project_user_id,
                                Project.slug == new_slug,
                            )
                        )
                    ).scalar_one_or_none()
                    if taken is not None:
                        new_slug = _disambig_slug(base_slug, cwd)

                    if dry_run:
                        target_id = "<new>"
                        detail["splits"].append(
                            {
                                "cwd": cwd,
                                "to_slug": new_slug,
                                "sessions": len(ingest_ids),
                                "reused": False,
                            }
                        )
                    else:
                        new_proj = Project(
                            id=str(uuid4()),
                            user_id=project_user_id,
                            slug=new_slug,
                            name=_dir_name(cwd) or project_name,
                            cwd=cwd,
                            created_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        )
                        db.add(new_proj)
                        await db.commit()
                        target_id = new_proj.id
                        report["new_projects"] += 1
                        detail["splits"].append(
                            {
                                "cwd": cwd,
                                "to_slug": new_slug,
                                "sessions": len(ingest_ids),
                                "reused": False,
                            }
                        )

            if not dry_run and target_id and target_id != "<new>":
                async with async_session() as db:
                    await db.execute(
                        update(RawSession)
                        .where(RawSession.ingest_id.in_(ingest_ids))
                        .values(project_id=target_id)
                    )
                    await db.commit()
            report["sessions_moved"] += len(ingest_ids)

        if had_split:
            report["projects_split"] += 1
        report["details"].append(detail)

    return report
