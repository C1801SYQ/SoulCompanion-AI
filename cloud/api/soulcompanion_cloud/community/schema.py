"""Independent PC03 schema constants; importing this module performs no I/O."""

from types import MappingProxyType

from ..family_identity import (
    FAMILY_MARKER_ID,
    FAMILY_SCHEMA_CHECKSUM,
    FAMILY_SCHEMA_OWNER,
    FAMILY_SCHEMA_VERSION,
    PHASE04_SCHEMA_CHECKSUM,
)


COMMUNITY_MARKER_ID = "pc03-parent-community"
COMMUNITY_SCHEMA_OWNER = "SoulCompanion-AI/pc03"
COMMUNITY_SCHEMA_VERSION = 3
COMMUNITY_SCHEMA_CHECKSUM = "af5041450e947fc043e29d529bb02e83ab71115ad19c0367ea2a3ab6a64aed34"
SCHEMA_COLLECTION = "sc_v2_app_schema"
COMMUNITY_COLLECTIONS = MappingProxyType({
    "content": "sc_v2_community_content",
    "relations": "sc_v2_community_relations",
    "content_reports": "sc_v2_community_content_reports",
    "role_bindings": "sc_v2_community_role_bindings",
    "write_quotas": "sc_v2_community_write_quotas",
})
# Immutable dependency tuples: marker id, owner, canonical manifest hash, version.
COMMUNITY_BASE_MARKERS = (
    ("phase04", "SoulCompanion-AI/phase04", PHASE04_SCHEMA_CHECKSUM, 1),
    (FAMILY_MARKER_ID, FAMILY_SCHEMA_OWNER, FAMILY_SCHEMA_CHECKSUM, FAMILY_SCHEMA_VERSION),
)
