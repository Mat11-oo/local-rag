from __future__ import annotations

from contextvars import ContextVar


DEFAULT_SCOPE = "00000000-0000-0000-0000-000000000001"
_workspace_context: ContextVar[str] = ContextVar("workspace_id", default=DEFAULT_SCOPE)


def current_workspace_id() -> str:
    return _workspace_context.get()


def activate_workspace(workspace_id: str) -> None:
    _workspace_context.set(workspace_id)
