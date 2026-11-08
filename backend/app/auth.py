"""Authentication via Cloudflare Access.

Access sits in front of the app and handles login (email one-time PIN). Every request that
reaches the origin carries a signed JWT in the ``Cf-Access-Jwt-Assertion`` header. The app
never stores passwords; it only verifies that JWT against the Access team's public keys and
reads the email from it (PLAN.md §5.4).

Service tokens (the iOS Shortcut, Phase 1) produce JWTs with a ``common_name`` instead of an
email. They are recognised here but only accepted by endpoints that opt in.
"""

import logging
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User

log = logging.getLogger("wander.auth")

ACCESS_HEADER = "Cf-Access-Jwt-Assertion"
ACCESS_COOKIE = "CF_Authorization"


@dataclass(frozen=True)
class Principal:
    email: str | None  # set for people
    service_id: str | None = None  # set for Access service tokens


class AccessVerifier:
    def __init__(self, team_domain: str, aud: str, jwks_client: PyJWKClient | None = None):
        self.issuer = f"https://{team_domain}"
        self.aud = aud
        self.jwks = jwks_client or PyJWKClient(
            f"{self.issuer}/cdn-cgi/access/certs", cache_keys=True, lifespan=3600
        )

    def verify(self, token: str) -> Principal:
        signing_key = self.jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self.aud,
            issuer=self.issuer,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
        if email := claims.get("email"):
            return Principal(email=email.lower())
        if common_name := claims.get("common_name"):
            return Principal(email=None, service_id=common_name)
        raise jwt.InvalidTokenError("token has neither email nor common_name")


def _token_from(request: Request) -> str | None:
    return request.headers.get(ACCESS_HEADER) or request.cookies.get(ACCESS_COOKIE)


def resolve_principal(request: Request) -> Principal:
    settings: Settings = request.app.state.settings
    if settings.dev_mode:
        return Principal(email=settings.dev_user_email.lower())

    verifier: AccessVerifier | None = request.app.state.access_verifier
    if verifier is None:
        # Neither Access nor dev mode configured: refuse everything rather than run open.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "authentication not configured")

    token = _token_from(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing Access token")
    try:
        principal = verifier.verify(token)
    except jwt.PyJWTError as exc:
        # Log why (never the token itself): a misconfigured team domain or AUD looks identical
        # to a forged token from the outside.
        log.warning("rejected Access token: %s: %s", type(exc).__name__, exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid Access token") from exc

    allowed = settings.allowed_email_set
    if principal.email and allowed and principal.email not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "email not allowed")
    return principal


def get_db(request: Request):
    with request.app.state.sessionmaker() as session:
        yield session


def _default_display_name(email: str) -> str:
    local = email.split("@", 1)[0]
    return local.replace(".", " ").replace("_", " ").title()


def _user_for(db: Session, email: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, display_name=_default_display_name(email))
        db.add(user)
        db.commit()
    return user


def current_user(
    principal: Principal = Depends(resolve_principal), db: Session = Depends(get_db)
) -> User:
    """A person (not a service token). Creates the user row on first sight."""
    if principal.email is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "a personal login is required here")
    return _user_for(db, principal.email)


def capturing_user(
    request: Request,
    principal: Principal = Depends(resolve_principal),
    db: Session = Depends(get_db),
) -> User:
    """Like current_user, but also accepts a configured service token (the iOS Shortcut), which
    saves on behalf of the person it's mapped to. Only the capture endpoint uses this."""
    if principal.email is not None:
        return _user_for(db, principal.email)
    settings = request.app.state.settings
    email = settings.service_token_map.get(principal.service_id or "")
    if not email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this service token can't save captures")
    allowed = settings.allowed_email_set
    if allowed and email not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "email not allowed")
    return _user_for(db, email)
