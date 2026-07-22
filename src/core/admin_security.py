"""Identitäts- und Datenschutzgrenze für das private Control Center."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
from typing import Iterable

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


TAILSCALE_LOGIN_HEADER = "tailscale-user-login"
LOOPBACKS = {"127.0.0.1", "::1", "localhost", "testclient"}


def _users(name: str) -> set[str]:
    return {
        value.strip().casefold()
        for value in os.getenv(name, "").split(",")
        if value.strip()
    }


@dataclass(frozen=True)
class AdminIdentity:
    login: str
    role: str
    source: str


class RemoteAdminAuthMiddleware(BaseHTTPMiddleware):
    """Vertraut Tailscale-Headern nur vom lokalen Serve-Reverse-Proxy."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        peer = request.client.host if request.client else ""
        tailscale_login = request.headers.get(TAILSCALE_LOGIN_HEADER, "").strip().casefold()
        if tailscale_login and peer not in LOOPBACKS:
            return JSONResponse({"detail": "Untrusted identity proxy"}, status_code=403)

        if tailscale_login:
            admins = _users("REMOTE_ADMIN_USERS")
            operators = _users("REMOTE_OPERATOR_USERS")
            viewers = _users("REMOTE_VIEWER_USERS")
            if admins or operators or viewers:
                if tailscale_login in admins:
                    role = "admin"
                elif tailscale_login in operators:
                    role = "operator"
                elif tailscale_login in viewers:
                    role = "viewer"
                else:
                    return JSONResponse({"detail": "Tailnet user is not authorized"}, status_code=403)
            else:
                return JSONResponse(
                    {"detail": "REMOTE_ADMIN_USERS allowlist is not configured"}, status_code=503
                )
            identity = AdminIdentity(tailscale_login, role, "tailscale-serve")
        elif peer in LOOPBACKS and os.getenv("REMOTE_ADMIN_ALLOW_LOCAL", "1") == "1":
            identity = AdminIdentity("local-console", "admin", "loopback")
        else:
            return JSONResponse(
                {"detail": "Private control center authentication required"}, status_code=401
            )

        request.state.admin_identity = identity
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'"
        )
        return response


def require_role(request: Request, allowed: Iterable[str]) -> AdminIdentity:
    identity = getattr(request.state, "admin_identity", None)
    if identity is None or identity.role not in set(allowed):
        raise HTTPException(status_code=403, detail="Insufficient control center role")
    return identity


def mask_identifier(value: object, visible: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= visible:
        return "*" * len(text)
    return "*" * (len(text) - visible) + text[-visible:]


def safe_contact_entity(entity: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "entity_id": entity.get("entity_id"), "canonical_name": entity.get("canonical_name"),
        "role": entity.get("role"), "alias_count": entity.get("alias_count"),
        "evidence_count": entity.get("evidence_count"),
        "tax_id": mask_identifier(entity.get("tax_id")),
        "iban": mask_identifier(entity.get("iban")),
        "email": mask_identifier(entity.get("email")),
    }


def safe_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "job_id": job.get("job_id"), "status": job.get("status"),
        "page_start": job.get("page_start"), "page_end": job.get("page_end"),
        "attempt_count": job.get("attempt_count"), "updated_at": job.get("updated_at"),
        "leased": bool(job.get("locked_by")),
        "source_hash": mask_identifier(job.get("source_md5"), 8),
    }


def resolve_allowed_path(requested: Path, roots: Iterable[Path]) -> Path:
    resolved = requested.expanduser().resolve()
    allowed = [Path(root).expanduser().resolve() for root in roots]
    if not any(resolved == root or root in resolved.parents for root in allowed):
        raise ValueError("Path is outside configured roots")
    return resolved
