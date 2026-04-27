from __future__ import annotations

"""MCP tool: recommend — surface high-confidence instincts + ECC skill suggestions."""

from typing import Annotated, Any

from pydantic import BaseModel, Field

RECOMMEND_DESC = (
    "Show learned behavioral instincts and skill suggestions based on your session patterns. "
    "High-confidence instincts become skill recommendations."
)

CONTRADICT_DESC = (
    "Mark an instinct as wrong to decay its confidence. Use instinct_id from recommend."
)


class RecommendInput(BaseModel):
    domain: Annotated[
        str | None,
        Field(
            description="Filter by domain: code-style, testing, git, debugging, etc.", max_length=40
        ),
    ] = None
    min_confidence: Annotated[
        float,
        Field(description="Minimum confidence threshold (0.0–0.9)", ge=0.0, le=0.9),
    ] = 0.0
    promoted_only: Annotated[
        bool,
        Field(description="Only return promoted instincts ready for skill suggestion"),
    ] = False
    limit: Annotated[int, Field(description="Max results", ge=1, le=20)] = 10


class ContradictInput(BaseModel):
    instinct_id: Annotated[
        str,
        Field(description="instinct_id to decay (get from recommend)", max_length=36),
    ]


async def handle_recommend(
    args: RecommendInput,
    user_id: str,
    project_id: str,
    instincts_store,
) -> dict[str, Any]:
    if args.promoted_only:
        instincts = await instincts_store.get_recommendations(
            user_id=user_id,
            project_id=project_id,
            limit=args.limit,
        )
    else:
        instincts = await instincts_store.list_instincts(
            user_id=user_id,
            project_id=project_id,
            domain=args.domain,
            min_confidence=args.min_confidence,
            limit=args.limit,
        )
        for inst in instincts:
            from piloci.storage.instincts_store import DOMAIN_SKILL_MAP

            inst["suggested_skills"] = DOMAIN_SKILL_MAP.get(inst.get("domain", "other"), [])

    return {
        "instincts": instincts,
        "total": len(instincts),
        "hint": (
            "Use contradict tool with instinct_id to lower confidence on wrong patterns. "
            "Instincts with count>=3 and confidence>=0.6 appear as skill suggestions."
        ),
    }


async def handle_contradict(
    args: ContradictInput,
    user_id: str,
    project_id: str,
    instincts_store,
) -> dict[str, Any]:
    ok = await instincts_store.contradict(
        user_id=user_id,
        project_id=project_id,
        instinct_id=args.instinct_id,
    )
    if not ok:
        return {"success": False, "error": f"instinct_id '{args.instinct_id}' not found"}
    return {"success": True, "action": "confidence_decayed", "instinct_id": args.instinct_id}
