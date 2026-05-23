"""CORS and CSRF helpers for cookie-based authentication.

Pass to ``bridge.asgi(middleware=[...])``::

    from pybridge.security import cors, csrf

    app = bridge.asgi(middleware=[
        cors(origins=["http://localhost:5173"], credentials=True),
        csrf(cookie_name="pyb_csrf"),
    ])
"""

from __future__ import annotations

import secrets

from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


def cors(
    *,
    origins: list[str] | str = "*",
    credentials: bool = False,
    methods: list[str] = ("POST", "GET", "OPTIONS"),
    headers: list[str] = ("content-type", "authorization", "x-csrf-token"),
) -> Middleware:
    """Build a CORS middleware configured for PyBridge.

    Use ``credentials=True`` together with a concrete origin list when you want
    the browser to send/receive cookies on cross-origin requests. The browser
    will reject ``Access-Control-Allow-Origin: *`` combined with credentials,
    so we never silently allow that combination.
    """
    allow_origins = [origins] if isinstance(origins, str) else list(origins)
    if credentials and allow_origins == ["*"]:
        raise ValueError(
            "cors(credentials=True) cannot be combined with origins='*'; "
            "browsers reject this combination. Pass a concrete origin list."
        )
    return Middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=credentials,
        allow_methods=list(methods),
        allow_headers=list(headers),
    )


# ---------------------------------------------------------------------------
# CSRF: double-submit cookie pattern
# ---------------------------------------------------------------------------


class _CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        cookie_name: str,
        header_name: str,
        same_site: str,
        secure: bool,
        protect_paths: tuple[str, ...],
    ) -> None:
        super().__init__(app)
        self.cookie_name = cookie_name
        self.header_name = header_name.lower()
        self.same_site = same_site
        self.secure = secure
        self.protect_paths = protect_paths

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        needs_check = (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and any(path.startswith(p) for p in self.protect_paths)
        )
        if needs_check:
            cookie_val = request.cookies.get(self.cookie_name)
            header_val = request.headers.get(self.header_name)
            if not cookie_val or not header_val or not secrets.compare_digest(cookie_val, header_val):
                response = JSONResponse(
                    {"error": {"code": "CSRF_FAILED", "message": "CSRF token missing or mismatched"}},
                    status_code=403,
                )
                self._issue_cookie_if_missing(request, response)
                return response

        response = await call_next(request)
        self._issue_cookie_if_missing(request, response)
        return response

    def _issue_cookie_if_missing(self, request: Request, response) -> None:
        if request.cookies.get(self.cookie_name):
            return
        token = secrets.token_urlsafe(32)
        response.set_cookie(
            self.cookie_name,
            token,
            samesite=self.same_site,
            secure=self.secure,
            httponly=False,  # client JS must read it to echo into the header
            path="/",
        )


def csrf(
    *,
    cookie_name: str = "pyb_csrf",
    header_name: str = "x-csrf-token",
    same_site: str = "lax",
    secure: bool = False,
    protect_paths: tuple[str, ...] = ("/rpc/",),
) -> Middleware:
    """Double-submit cookie CSRF protection.

    The server issues a random token in a non-HttpOnly cookie. The TS client
    reads that cookie and echoes the value in ``X-CSRF-Token`` on every
    mutating request. Without the same value in both places, the request is
    rejected with HTTP 403.

    Pair with cookie-based session auth. Bearer-token clients don't need this
    (the attacker can't read the bearer token from a third-party origin, so
    CSRF doesn't apply).
    """
    return Middleware(
        _CSRFMiddleware,
        cookie_name=cookie_name,
        header_name=header_name,
        same_site=same_site,
        secure=secure,
        protect_paths=protect_paths,
    )
