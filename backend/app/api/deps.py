"""API dependencies: runtime access + token authentication."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from app.runtime import Runtime


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def get_config(request: Request):
    return request.app.state.config


def require_token(
    request: Request,
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
    authorization: str | None = Header(default=None),
) -> None:
    """Authentication for control (mutating) endpoints.

    Token source: config file security.api_token or env SRSRAN_API_TOKEN.
    If no token is configured, control endpoints are DISABLED (fail closed).
    Accepted headers: X-API-Token: <token>  or  Authorization: Bearer <token>
    """
    config = request.app.state.config
    expected = config.security.api_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="control API disabled: no API token configured "
                   "(set security.api_token or SRSRAN_API_TOKEN)",
        )
    provided = x_api_token
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization.split(" ", 1)[1].strip()
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid API token",
        )
