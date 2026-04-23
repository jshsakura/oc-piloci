"""Schema compaction: strip Pydantic noise to minimize LLM context tokens."""

from typing import Any

_MAX_PARAM_DESC = 80
_MAX_DEFAULT_STR = 60


def compact_schema(schema: Any, *, _top: bool = False) -> Any:
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for k, v in schema.items():
            if k == "title":
                continue
            if k == "description" and _top:
                continue
            if k == "description" and isinstance(v, str) and len(v) > _MAX_PARAM_DESC:
                v = v[:_MAX_PARAM_DESC]
            if k == "default" and isinstance(v, str) and len(v) > _MAX_DEFAULT_STR:
                continue
            # Flatten anyOf nullable unions: [{"type": "X"}, {"type": "null"}] → {"type": "X"}
            if k == "anyOf" and isinstance(v, list):
                non_null = [i for i in v if i != {"type": "null"}]
                if len(non_null) == 1:
                    out.update(compact_schema(non_null[0]))
                    continue
            out[k] = compact_schema(v)
        return out
    if isinstance(schema, list):
        return [compact_schema(i) for i in schema]
    return schema
