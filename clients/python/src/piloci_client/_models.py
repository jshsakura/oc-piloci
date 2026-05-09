"""Typed return models for piloci-client.

Every model exposes a `.raw` attribute with the original parsed JSON dict
for forward-compatibility (new server fields won't break existing code).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

# ---------------------------------------------------------------------------
# Memory / Recall
# ---------------------------------------------------------------------------


@dataclass
class MemoryResult:
    """Returned by memory.save() and memory.delete()."""

    success: bool
    action: str  # "save" or "forget"
    memory_id: Optional[str] = None
    project_id: Optional[str] = None
    error: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryResult":
        return cls(
            success=data.get("success", False),
            action=data.get("action", ""),
            memory_id=data.get("memory_id"),
            project_id=data.get("project_id"),
            error=data.get("error"),
            raw=data,
        )


@dataclass
class RecallPreview:
    """Single memory preview returned in a recall response."""

    id: str
    score: float
    tags: List[str]
    excerpt: str
    length: int
    created_at: Optional[str] = None
    # Full content — only populated when fetch_ids was used
    content: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecallPreview":
        return cls(
            id=data.get("id", data.get("memory_id", "")),
            score=float(data.get("score", 0.0)),
            tags=list(data.get("tags") or []),
            excerpt=data.get("excerpt", data.get("content", "")[:80]),
            length=data.get("length", len(data.get("content", ""))),
            created_at=data.get("created_at"),
            content=data.get("content"),
            raw=data,
        )


@dataclass
class RecallResult:
    """Returned by client.recall()."""

    mode: str  # "preview", "full", or "file"
    total: int
    previews: List[RecallPreview]
    profile: Optional[dict[str, Any]] = None
    file: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecallResult":
        raw_items = data.get("memories") or data.get("previews") or []
        return cls(
            mode=data.get("mode", "preview"),
            total=data.get("total", len(raw_items)),
            previews=[RecallPreview.from_dict(m) for m in raw_items],
            profile=data.get("profile"),
            file=data.get("file"),
            raw=data,
        )


# ---------------------------------------------------------------------------
# Projects / Init
# ---------------------------------------------------------------------------


@dataclass
class Project:
    """A single piLoci project."""

    id: str
    name: str
    slug: str
    cwd: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            slug=data.get("slug", ""),
            cwd=data.get("cwd"),
            raw=data,
        )


@dataclass
class ProjectListResult:
    """Returned by projects.list()."""

    projects: List[Project]
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectListResult":
        return cls(
            projects=[Project.from_dict(p) for p in data.get("projects", [])],
            raw=data,
        )


@dataclass
class InitResult:
    """Returned by projects.init()."""

    success: bool
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    anchor: Optional[str] = None
    files: Optional[dict[str, str]] = None
    instructions: Optional[str] = None
    error: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InitResult":
        return cls(
            success=data.get("success", False),
            project_id=data.get("project_id"),
            project_name=data.get("project_name"),
            anchor=data.get("anchor"),
            files=data.get("files"),
            instructions=data.get("instructions"),
            error=data.get("error"),
            raw=data,
        )


# ---------------------------------------------------------------------------
# WhoAmI
# ---------------------------------------------------------------------------


@dataclass
class WhoAmI:
    """Returned by client.whoami()."""

    user_id: str
    project_id: Optional[str] = None
    email: Optional[str] = None
    scope: Optional[str] = None
    session_id: Optional[str] = None
    client: Optional[dict[str, Any]] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WhoAmI":
        return cls(
            user_id=data.get("userId", ""),
            project_id=data.get("projectId"),
            email=data.get("email"),
            scope=data.get("scope"),
            session_id=data.get("sessionId"),
            client=data.get("client"),
            raw=data,
        )


# ---------------------------------------------------------------------------
# Instincts: Recommend / Contradict
# ---------------------------------------------------------------------------


@dataclass
class Instinct:
    """A single behavioral instinct entry."""

    instinct_id: str
    domain: Optional[str] = None
    pattern: Optional[str] = None
    confidence: float = 0.0
    count: int = 0
    promoted: bool = False
    suggested_skills: List[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Instinct":
        return cls(
            instinct_id=data.get("instinct_id", ""),
            domain=data.get("domain"),
            pattern=data.get("pattern"),
            confidence=float(data.get("confidence", 0.0)),
            count=int(data.get("count", 0)),
            promoted=bool(data.get("promoted", False)),
            suggested_skills=list(data.get("suggested_skills") or []),
            raw=data,
        )


@dataclass
class RecommendResult:
    """Returned by client.recommend()."""

    instincts: List[Instinct]
    total: int
    hint: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecommendResult":
        return cls(
            instincts=[Instinct.from_dict(i) for i in data.get("instincts", [])],
            total=data.get("total", 0),
            hint=data.get("hint"),
            raw=data,
        )


@dataclass
class ContradictResult:
    """Returned by client.contradict()."""

    success: bool
    action: Optional[str] = None
    instinct_id: Optional[str] = None
    error: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContradictResult":
        return cls(
            success=data.get("success", False),
            action=data.get("action"),
            instinct_id=data.get("instinct_id"),
            error=data.get("error"),
            raw=data,
        )
