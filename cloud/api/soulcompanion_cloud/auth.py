"""Verify access tokens with CloudBase; token payloads are never locally trusted."""

from dataclasses import dataclass, field
from typing import Protocol

import httpx

from .config import Settings
from .errors import CloudError, unavailable


@dataclass(frozen=True)
class AppPrincipal:
    subject: str = field(repr=False)
    issuer: str
    provider: str = "cloudbase_auth"


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> AppPrincipal: ...
    async def ready(self) -> bool: ...


class CloudBaseTokenVerifier:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def ready(self) -> bool:
        # There is no anonymous credential probe: readiness reports configured auth,
        # while every private request performs online introspection, including revocation.
        return bool(self.settings.env_id)

    async def verify(self, token: str) -> AppPrincipal:
        if not self.settings.env_id:
            raise unavailable()
        try:
            response = await self.client.get(
                f"{self.settings.cloudbase_base_url}/auth/v1/token/introspect",
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.settings.upstream_timeout_seconds,
            )
        except httpx.HTTPError:
            raise unavailable() from None
        if response.status_code in {401, 403}:
            raise CloudError(401, "unauthorized", "Please sign in again.")
        if response.status_code != 200:
            raise unavailable()
        try:
            data = response.json()
        except ValueError:
            raise unavailable() from None
        if data == {}:
            raise CloudError(401, "unauthorized", "Please sign in again.")
        if not isinstance(data, dict):
            raise unavailable()
        subject = data.get("sub")
        token_type = data.get("token_type")
        if (
            not isinstance(subject, str)
            or not subject
            or len(subject) > 256
            or not isinstance(token_type, str)
            or token_type.lower() != "bearer"
        ):
            raise CloudError(401, "unauthorized", "Please sign in again.")
        # Introspection defaults client_id to this environment. Explicit mismatches
        # are rejected, preventing cross-environment identity reuse.
        if data.get("client_id") != self.settings.env_id:
            raise CloudError(401, "unauthorized", "Please sign in again.")
        return AppPrincipal(subject=subject, issuer=self.settings.env_id)
