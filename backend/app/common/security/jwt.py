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
    """Аутентифицированный пользователь (маппинг на users.keycloak_sub — синхронизация при входе)."""

    sub: str
    username: str
    display_name: str
    email: str | None
    is_local: bool
    realm_roles: frozenset[str] = frozenset()  # realm_access.roles (ПРВ-5: kb-admin)


class _JwksCache:
    """Простой TTL-кэш JWKS (в MVP достаточно; Valkey-кэш — при масштабировании)."""

    def __init__(self) -> None:
        self._keys: dict[str, Any] = {}
        self._expires_at: float = 0.0

    def get(self) -> dict[str, Any]:
        settings = get_settings()
        now = time.monotonic()
        if not self._keys or now >= self._expires_at:
            # JWKS: внутренний base (контейнер → keycloak), fallback на issuer
            base = settings.keycloak_internal_base or settings.keycloak_issuer
            resp = httpx.get(f"{base}/protocol/openid-connect/certs", timeout=5.0)
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
            options={
                "require_aud": False,  # aud проверяем сами (пересечение списков, python-jose строг)
                "require_exp": True,
                "verify_signature": True,
                "verify_aud": False,
                "verify_iss": True,
            },
            issuer=settings.keycloak_issuer,
        )
        token_aud = claims.get("aud")
        allowed = settings.keycloak_audiences.split(",")
        auds = token_aud if isinstance(token_aud, list) else [token_aud]
        if not (set(auds) & set(allowed)):
            raise JWTError(f"audience {token_aud} не входит в допустимые {allowed}")
        if not token_aud:
            raise JWTError("aud отсутствует")
    except JWTError as e:
        raise PermissionDenied(f"Токен не прошёл проверку: {e}") from e

    return Principal(
        sub=str(claims["sub"]),
        username=str(claims.get("preferred_username", claims["sub"])),
        display_name=str(claims.get("name", claims.get("preferred_username", claims["sub"]))),
        email=claims.get("email"),
        is_local=True,  # LDAP/Kerberos — отложены (АУТ-3); уточняется при синхронизации users
        realm_roles=frozenset(claims.get("realm_access", {}).get("roles", [])),
    )
