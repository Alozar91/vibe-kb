"""Проверка JWT и извлечение текущего пользователя (АУТ-5, code-standards §2.1).

Keycloak realm `corp-kb`, клиенты kb-web/kb-rag/kb-mcp (auth-setup.md).
JWKS кэшируется (KB_JWKS_CACHE_TTL); проверка — подпись, issuer, audience, exp.
"""

import time
from dataclasses import dataclass
from typing import Any

import httpx
from jose import JWTError, jwt

from app.common.config import get_settings
from app.common.errors import PermissionDenied


@dataclass(frozen=True)
class Principal:
    """Аутентифицированный пользователь (маппинг на users.keycloak_sub — на Этапе 1)."""

    sub: str
    username: str
    display_name: str
    email: str | None
    is_local: bool


class _JwksCache:
    """Простой TTL-кэш JWKS (в MVP достаточно; Valkey-кэш — при масштабировании)."""

    def __init__(self) -> None:
        self._keys: dict[str, Any] = {}
        self._expires_at: float = 0.0

    def get(self) -> dict[str, Any]:
        settings = get_settings()
        now = time.monotonic()
        if not self._keys or now >= self._expires_at:
            resp = httpx.get(f"{settings.keycloak_issuer}/protocol/openid-connect/certs", timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            self._keys = {k["kid"]: k for k in data.get("keys", [])}
            self._expires_at = now + settings.jwks_cache_ttl
        return self._keys


_jwks = _JwksCache()


def verify_token(token: str) -> Principal:
    """Проверить access-token и вернуть Principal; ошибка → PermissionDenied (401 на краю API)."""

    settings = get_settings()
    try:
        header = jwt.get_unverified_header(token)
        keys = _jwks.get()
        key = keys.get(header.get("kid", ""))
        if key is None:
            raise JWTError("kid не найден в JWKS")
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.keycloak_audiences.split(","),
            issuer=settings.keycloak_issuer,
            options={"require_aud": True, "require_exp": True, "verify_signature": True},
        )
    except JWTError as e:
        raise PermissionDenied(f"Токен не прошёл проверку: {e}") from e

    return Principal(
        sub=str(claims["sub"]),
        username=str(claims.get("preferred_username", claims["sub"])),
        display_name=str(claims.get("name", claims.get("preferred_username", claims["sub"]))),
        email=claims.get("email"),
        is_local=True,  # LDAP/Kerberos — отложены (АУТ-3); уточняется при синхронизации users
    )
