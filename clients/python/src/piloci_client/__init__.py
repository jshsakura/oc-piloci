"""piloci-client — Python SDK for the piLoci self-hosted memory service.

Quick start::

    from piloci_client import Piloci

    client = Piloci(base_url="https://my.piloci", token="JWT.xxx")
    client.memory.save(content="we decided to use argon2id", tags=["security"])
    results = client.recall(query="what auth did we pick?", limit=5)
    for p in results.previews:
        print(p.excerpt)

For async usage import ``AsyncPiloci`` instead.
"""

from ._async_client import AsyncPiloci
from ._client import Piloci
from ._errors import (
    PilociAuthError,
    PilociError,
    PilociPermissionError,
    PilociServerError,
    PilociValidationError,
)
from ._models import (
    ContradictResult,
    InitResult,
    Instinct,
    MemoryResult,
    Project,
    ProjectListResult,
    RecallPreview,
    RecallResult,
    RecommendResult,
    WhoAmI,
)

__version__ = "0.1.0"

__all__ = [
    # Clients
    "Piloci",
    "AsyncPiloci",
    # Errors
    "PilociError",
    "PilociAuthError",
    "PilociPermissionError",
    "PilociValidationError",
    "PilociServerError",
    # Models
    "MemoryResult",
    "RecallResult",
    "RecallPreview",
    "Project",
    "ProjectListResult",
    "InitResult",
    "WhoAmI",
    "Instinct",
    "RecommendResult",
    "ContradictResult",
]
