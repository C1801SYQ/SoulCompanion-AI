"""Independent PC02 identity metadata; never provisions CloudBase resources."""

from typing import Literal
import unicodedata
from uuid import UUID, uuid5


ChildAgeBand = Literal["0-2", "3-5", "6-8", "9-12", "13-15", "16-18"]
FAMILY_MARKER_ID = "pc02-family-identity"
FAMILY_SCHEMA_OWNER = "SoulCompanion-AI/pc02"
FAMILY_SCHEMA_VERSION = 2
PHASE04_SCHEMA_CHECKSUM = "7e23a3c17a1551df1d5a3c7c7c9deb8903f9ea7430fbd38e4fa482e85159fa49"
FAMILY_SCHEMA_CHECKSUM = "6462a3674be5331748cf5715d81b78dd7c687a6ee326e7a0d95b253c29751324"
PARENT_PROFILE_NAMESPACE = UUID("1cb624ae-8152-4d40-aad7-a0f48f54a933")


def parent_profile_id(owner: str) -> str:
    """A distinct public UUID converges across first saves for one verified owner."""
    return str(uuid5(PARENT_PROFILE_NAMESPACE, owner))


def normalize_community_nickname(value: str) -> str:
    # Check before trimming so surrounding control characters cannot be hidden.
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("Community nickname contains unsupported characters.")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not 2 <= len(normalized) <= 24:
        raise ValueError("Community nickname requires 2 to 24 characters.")
    if any(
        unicodedata.category(character)[0] not in {"L", "M", "N"} and character not in " ·_-"
        for character in normalized
    ):
        raise ValueError("Community nickname contains unsupported characters.")
    return normalized
