"""Only explicit deployment environment variables configure production access."""

from dataclasses import dataclass, field
import os
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    env_id: str = ""
    allowed_origins: tuple[str, ...] = ()
    api_key: str = field(default="", repr=False)
    max_body_bytes: int = 16384
    health_rate_limit: int = 20
    private_rate_limit: int = 60
    preauth_rate_limit: int = 120
    rate_window_seconds: int = 60
    upstream_timeout_seconds: float = 1.2
    request_timeout_seconds: float = 2.6

    def __post_init__(self):
        if self.env_id and not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", self.env_id):
            raise ValueError("Invalid CloudBase environment ID")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            local = parsed.hostname in {"127.0.0.1", "localhost", "[::1]", "::1"}
            if (
                parsed.scheme not in ({"http", "https"} if local else {"https"})
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
                or "*" in origin
                or any(character.isspace() for character in origin)
            ):
                raise ValueError(
                    "CORS must use exact HTTPS origins (HTTP allowed only for localhost)"
                )
        if not 1 <= self.max_body_bytes <= 65536:
            raise ValueError("Body limit must be bounded")
        if not all(
            1 <= value <= 10000
            for value in (
                self.health_rate_limit,
                self.private_rate_limit,
                self.preauth_rate_limit,
                self.rate_window_seconds,
            )
        ):
            raise ValueError("Rate limits must be bounded")
        if not 0 < self.upstream_timeout_seconds <= self.request_timeout_seconds <= 60:
            raise ValueError("Request deadlines must be bounded")

    @property
    def cloudbase_base_url(self) -> str:
        return f"https://{self.env_id}.api.tcloudbasegateway.com"

    @classmethod
    def from_environment(cls):
        return cls(
            env_id=os.environ.get("CLOUDBASE_ENV_ID", ""),
            api_key=os.environ.get("CLOUDBASE_APIKEY", ""),
            allowed_origins=tuple(
                filter(
                    None,
                    (
                        item.strip()
                        for item in os.environ.get("CLOUD_ALLOWED_ORIGINS", "").split(
                            ","
                        )
                    ),
                )
            ),
        )
