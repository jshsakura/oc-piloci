"""Synchronous Piloci client."""

from __future__ import annotations

from typing import Any, List, Optional

import httpx

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
    MemoryResult,
    ProjectListResult,
    RecallResult,
    RecommendResult,
    WhoAmI,
)

_VERSION = "0.1.0"
_USER_AGENT = f"piloci-client-python/{_VERSION}"


def _raise_for_status(response: httpx.Response) -> None:
    """Map HTTP error status codes to typed exceptions."""
    if response.is_success:
        return
    try:
        body = response.json()
    except Exception:
        body = response.text

    code = response.status_code
    if code == 401:
        raise PilociAuthError(
            f"Authentication failed (401): {body}",
            status_code=code,
            raw=body,
        )
    if code == 403:
        raise PilociPermissionError(
            "Permission denied (403). Project-scoped operations require a token "
            "with a project_id claim. Generate one in piLoci Settings → Tokens.",
            status_code=code,
            raw=body,
        )
    if code == 422:
        raise PilociValidationError(
            f"Validation error (422): {body}",
            details=body,
            status_code=code,
            raw=body,
        )
    if 500 <= code < 600:
        raise PilociServerError(
            f"Server error ({code}): {body}",
            status_code=code,
            raw=body,
        )
    raise PilociError(f"Unexpected HTTP {code}: {body}", status_code=code, raw=body)


class _MemoryNamespace:
    """Namespace for memory operations: save, delete."""

    def __init__(self, client: "Piloci") -> None:
        self._c = client

    def save(
        self,
        content: str,
        tags: Optional[List[str]] = None,
        *,
        project: Optional[str] = None,
    ) -> MemoryResult:
        """Save a memory to the current project.

        Args:
            content: Text content to remember. Up to 200 000 chars.
            tags: Optional list of 1-3 short tags.
            project: Optional project hint sent as X-Piloci-Project header.

        Returns:
            MemoryResult with success, action, and memory_id.

        Raises:
            PilociPermissionError: If the token has no project_id claim.
            PilociAuthError: If the token is invalid or expired.
        """
        body: dict[str, Any] = {"action": "save", "content": content}
        if tags is not None:
            body["tags"] = tags
        return MemoryResult.from_dict(self._c._post("/api/v1/memory", body, project=project))

    def delete(
        self,
        memory_id: str,
        *,
        project: Optional[str] = None,
    ) -> MemoryResult:
        """Forget (delete) a memory by ID.

        Args:
            memory_id: The memory ID to remove. Obtain via recall().
            project: Optional project hint sent as X-Piloci-Project header.

        Returns:
            MemoryResult with success and action='forget'.

        Raises:
            PilociPermissionError: If the token has no project_id claim.
        """
        body: dict[str, Any] = {"action": "forget", "memory_id": memory_id, "content": ""}
        return MemoryResult.from_dict(self._c._post("/api/v1/memory", body, project=project))

    def list(
        self,
        query: str,
        limit: int = 5,
        tags: Optional[List[str]] = None,
        *,
        project: Optional[str] = None,
    ) -> RecallResult:
        """Convenience alias — search memories (delegates to recall).

        Args:
            query: Search query string.
            limit: Maximum number of results (1–50).
            tags: Optional tag filter.
            project: Optional project hint header.

        Returns:
            RecallResult with previews list.
        """
        return self._c.recall(query=query, limit=limit, tags=tags, project=project)


class _ProjectsNamespace:
    """Namespace for project operations: list, init."""

    def __init__(self, client: "Piloci") -> None:
        self._c = client

    def list(self, refresh: bool = False) -> ProjectListResult:
        """List all projects visible to the current token.

        Args:
            refresh: Force re-fetch bypassing the server-side 5-minute cache.

        Returns:
            ProjectListResult with a list of Project dataclasses.
        """
        params = {"refresh": "true"} if refresh else {}
        data = self._c._get("/api/v1/projects", params=params)
        return ProjectListResult.from_dict(data)

    def init(
        self,
        cwd: Optional[str] = None,
        project_name: Optional[str] = None,
    ) -> InitResult:
        """Run one-time project setup for a directory.

        Args:
            cwd: Current working directory path (pass $PWD / os.getcwd()).
            project_name: Human-readable project name. Defaults to folder name.

        Returns:
            InitResult containing CLAUDE.md / AGENTS.md content to write.
        """
        body: dict[str, Any] = {}
        if cwd is not None:
            body["cwd"] = cwd
        if project_name is not None:
            body["project_name"] = project_name
        return InitResult.from_dict(self._c._post("/api/v1/init", body))


class Piloci:
    """Synchronous piLoci REST client.

    Args:
        base_url: Base URL of your piLoci instance, e.g. ``https://my.piloci``.
        token: JWT bearer token. Generate in piLoci Settings → Tokens.
        timeout: Request timeout in seconds. Default 30.

    Example::

        from piloci_client import Piloci

        client = Piloci(base_url="https://my.piloci", token="JWT.xxx")
        client.memory.save(content="we decided to use argon2id", tags=["security"])
        results = client.recall(query="what auth did we pick?", limit=5)
        for p in results.previews:
            print(p.excerpt)
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._http = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": _USER_AGENT,
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        self.memory = _MemoryNamespace(self)
        self.projects = _ProjectsNamespace(self)

    def _project_headers(self, project: Optional[str]) -> dict[str, str]:
        if project:
            return {"X-Piloci-Project": project}
        return {}

    def _get(self, path: str, params: Optional[dict[str, str]] = None) -> dict[str, Any]:
        response = self._http.get(path, params=params)
        _raise_for_status(response)
        return response.json()

    def _post(
        self,
        path: str,
        body: dict[str, Any],
        project: Optional[str] = None,
    ) -> dict[str, Any]:
        headers = self._project_headers(project)
        response = self._http.post(path, json=body, headers=headers)
        _raise_for_status(response)
        return response.json()

    def recall(
        self,
        query: Optional[str] = None,
        fetch_ids: Optional[List[str]] = None,
        to_file: bool = False,
        include_profile: bool = True,
        tags: Optional[List[str]] = None,
        limit: int = 5,
        *,
        project: Optional[str] = None,
    ) -> RecallResult:
        """Search memories and return ranked previews.

        Args:
            query: Search query. Required unless fetch_ids is provided.
            fetch_ids: List of memory IDs to fetch in full (skips vector search).
            to_file: Ask the server to save results as a markdown file.
            include_profile: Include profile summary in results.
            tags: Filter results to memories with any of these tags.
            limit: Maximum number of preview results (1–50).
            project: Optional project hint sent as X-Piloci-Project header.

        Returns:
            RecallResult with .previews (list of RecallPreview) and optional .profile.

        Raises:
            PilociPermissionError: If the token has no project_id claim.
        """
        body: dict[str, Any] = {
            "to_file": to_file,
            "include_profile": include_profile,
            "limit": limit,
        }
        if query is not None:
            body["query"] = query
        if fetch_ids is not None:
            body["fetch_ids"] = fetch_ids
        if tags is not None:
            body["tags"] = tags
        return RecallResult.from_dict(self._post("/api/v1/recall", body, project=project))

    def whoami(self) -> WhoAmI:
        """Return information about the current token / session.

        Returns:
            WhoAmI with user_id, email, scope, project_id, etc.
        """
        return WhoAmI.from_dict(self._get("/api/v1/whoami"))

    def recommend(
        self,
        domain: Optional[str] = None,
        min_confidence: float = 0.0,
        promoted_only: bool = False,
        limit: int = 10,
        *,
        project: Optional[str] = None,
    ) -> RecommendResult:
        """Return learned behavioral instincts for the current project.

        Args:
            domain: Filter by domain (e.g. 'code-style', 'testing', 'git').
            min_confidence: Minimum confidence threshold (0.0–0.9).
            promoted_only: Only return instincts ready for skill suggestion.
            limit: Maximum number of results (1–20).
            project: Optional project hint sent as X-Piloci-Project header.

        Returns:
            RecommendResult with .instincts list.

        Raises:
            PilociPermissionError: If the token has no project_id claim.
        """
        body: dict[str, Any] = {
            "min_confidence": min_confidence,
            "promoted_only": promoted_only,
            "limit": limit,
        }
        if domain is not None:
            body["domain"] = domain
        return RecommendResult.from_dict(self._post("/api/v1/recommend", body, project=project))

    def contradict(
        self,
        instinct_id: str,
        *,
        project: Optional[str] = None,
    ) -> ContradictResult:
        """Mark an instinct as wrong to decay its confidence.

        Args:
            instinct_id: ID of the instinct to contradict (from recommend()).
            project: Optional project hint sent as X-Piloci-Project header.

        Returns:
            ContradictResult with success and action='confidence_decayed'.

        Raises:
            PilociPermissionError: If the token has no project_id claim.
        """
        body: dict[str, Any] = {"instinct_id": instinct_id}
        return ContradictResult.from_dict(self._post("/api/v1/contradict", body, project=project))

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    def __enter__(self) -> "Piloci":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
