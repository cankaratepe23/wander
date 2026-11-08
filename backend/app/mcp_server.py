"""Wander as a remote MCP server (PLAN.md §4.4), at /mcp, for the Claude app.

It exposes the same tools as in-app chat (app/tools.py). Long brainstorms then run on a Claude
subscription instead of API credit and write their results straight back into Wander. Cloudflare Access
(managed OAuth on its own hostname) stands in front; every request still carries an Access JWT, which
is verified here exactly like the API's, and the tools run as that person.
"""

import contextvars
import inspect
import json
from typing import Any

from fastapi import HTTPException
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app import tools
from app.auth import _user_for, resolve_principal

_email: contextvars.ContextVar[str] = contextvars.ContextVar("wander_mcp_email")

INSTRUCTIONS = (
    "Wander is a shared inbox of travel ideas saved by two people who travel together. Search it before "
    "answering questions about what they've saved, and use the tools to make the changes they ask for "
    "(fix places, save new ideas, shortlist, merge duplicates). Refer to ideas by title."
)


def _make_tool(app_state: Any, name: str, model: type, fn: Any):
    def call(**kwargs: Any) -> str:
        with app_state.sessionmaker() as db:
            user = _user_for(db, _email.get())
            out, is_error = tools.run(db, user, app_state.settings, name, kwargs)
        if is_error:
            raise ValueError(json.loads(out).get("error") or out)
        return out

    params = []
    annotations: dict[str, Any] = {}
    for field_name, field in model.model_fields.items():
        default = (
            inspect.Parameter.empty
            if field.is_required()
            else field.get_default(call_default_factory=True)
        )
        params.append(
            inspect.Parameter(
                field_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=field.annotation,
            )
        )
        annotations[field_name] = field.annotation
    annotations["return"] = str
    call.__signature__ = inspect.Signature(params, return_annotation=str)  # type: ignore[attr-defined]
    call.__annotations__ = annotations
    call.__name__ = name
    return call


def build(app_state: Any) -> tuple[MCPServer, ASGIApp]:
    server = MCPServer(name="Wander", instructions=INSTRUCTIONS)
    for name, (model, fn, _label) in tools.TOOLS.items():
        server.add_tool(
            _make_tool(app_state, name, model, fn),
            name=name,
            description=(model.__doc__ or "").strip(),
        )
    starlette_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        # Access already pins the hostname; DNS-rebinding checks would only reject the real host.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    handler = next(r.endpoint for r in starlette_app.routes if getattr(r, "path", None) == "/mcp")
    return server, AccessGate(handler)


class AccessGate:
    """Verify the caller like any API request (Access JWT, allow-list) before MCP sees the request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        try:
            principal = resolve_principal(request)
        except HTTPException as exc:
            await JSONResponse({"error": exc.detail}, status_code=exc.status_code)(
                scope, receive, send
            )
            return
        if principal.email is None:
            await JSONResponse({"error": "a personal login is required"}, status_code=403)(
                scope, receive, send
            )
            return
        token = _email.set(principal.email)
        try:
            await self.app(scope, receive, send)
        finally:
            _email.reset(token)
