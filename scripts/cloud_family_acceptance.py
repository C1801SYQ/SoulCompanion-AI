"""Explicit PC02 API acceptance using exactly two existing synthetic fixtures.

Default execution prints an offline plan. Real execution requires both flags;
credentials remain in memory and every public result is reconstructed from an
allowlist. No users, historical records, collections, or resources are deleted.
"""

import argparse
from datetime import datetime, timezone
import json
import math
import secrets
from typing import Any, Literal, TypedDict, cast, overload
from uuid import UUID

import httpx

from cloud_acceptance import (
    API_BASE,
    CLOUDBASE_BASE,
    AcceptanceError,
    FIXTURE_NAME_PATTERN,
    UID_PATTERN,
    PrivateHttp,
    SyntheticAccount,
    existing_fixture_accounts,
    login,
    payload,
    require,
    require_status,
    reset_fixture_password,
    revoke,
)
from cloud_admin import CLI_ENTRY, ENV_ID, REGION, CloudAdmin


PARENT_DATABASE_DENIAL_PATH = (
    "/v1/database/instances/(default)/databases/(default)/collections/sc_v2_parent_profiles/documents"
)
CHECK_NAMES = {
    "health_ready_anonymous_invalid_denial",
    "two_existing_cloudbase_principals_verified",
    "application_identity_mapping_distinct_stable",
    "pc02_capabilities_enabled",
    "parent_profile_public_dto_boundary",
    "parent_profile_saved_read_back_stable",
    "duplicate_parent_nicknames_distinct_ids",
    "client_identity_fields_rejected",
    "optional_child_age_create_read",
    "child_age_omission_update_clear",
    "invalid_child_age_rejected",
    "foreign_child_access_denied_b_empty",
    "parent_collection_direct_access_denied",
    "new_child_archived_verified",
    "issued_tokens_revoked_private_api_denied",
}
STAGES = {
    "preflight",
    "health_and_anonymous",
    "synthetic_authentication",
    "identity_and_capabilities",
    "parent_profiles",
    "child_age",
    "ownership_and_input_boundaries",
    "direct_database_denial",
    "cleanup",
    "complete",
}
PARENT_FIELDS = {"id", "nickname", "created_at", "updated_at"}
CHILD_FIELDS = {"id", "nickname", "age_band", "status", "created_at", "updated_at"}
SYNTHETIC_PARENT_NICKNAME = "PC02合成家长"


class ParentDTO(TypedDict):
    id: str
    nickname: str
    created_at: str
    updated_at: str


def require_uuid(value: object) -> None:
    try:
        valid = isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, AttributeError):
        valid = False
    require(valid, "PUBLIC_DTO_INVALID")


def require_utc(value: object) -> None:
    try:
        valid = (
            isinstance(value, str)
            and len(value) <= 64
            and datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() == timezone.utc.utcoffset(None)
        )
    except ValueError:
        valid = False
    require(valid, "PUBLIC_DTO_INVALID")


@overload
def parent_dto(response: httpx.Response, *, nullable: Literal[True]) -> ParentDTO | None: ...


@overload
def parent_dto(response: httpx.Response, *, nullable: Literal[False] = False) -> ParentDTO: ...


def parent_dto(response: httpx.Response, *, nullable: bool = False) -> ParentDTO | None:
    try:
        record = response.json()
    except ValueError:
        raise AcceptanceError("PUBLIC_DTO_INVALID") from None
    if record is None and nullable:
        return None
    require(isinstance(record, dict) and set(record) == PARENT_FIELDS, "PUBLIC_DTO_INVALID")
    require_uuid(record["id"])
    require(isinstance(record["nickname"], str) and 2 <= len(record["nickname"]) <= 24, "PUBLIC_DTO_INVALID")
    for field in ("created_at", "updated_at"):
        require_utc(record[field])
    return cast(ParentDTO, record)


def verify_parent_database_denial(http: PrivateHttp, account: SyntheticAccount) -> None:
    """One fixed denial probe extends no shared target or mutation allowlist."""
    require(bool(account.token), "AUTH_RESPONSE_INVALID")
    started = http.clock()
    try:
        response = http.client.request(
            "GET",
            CLOUDBASE_BASE + PARENT_DATABASE_DENIAL_PATH,
            headers={"Accept": "application/json", "Authorization": f"Bearer {account.token}"},
            params={"count": "true"},
            timeout=12,
            follow_redirects=False,
        )
    except httpx.HTTPError:
        raise AcceptanceError("HTTP_UNAVAILABLE") from None
    http.requests += 1
    http.max_latency_ms = max(http.max_latency_ms, math.ceil((http.clock() - started) * 1000))
    require_status(response, 401, 403)


class FamilyAcceptance:
    def __init__(self, admin: CloudAdmin, http: PrivateHttp) -> None:
        self.admin, self.http = admin, http
        self.stage = "preflight"
        self.checks: dict[str, bool] = {}
        self.accounts: list[SyntheticAccount] = []
        self.token_cleanup_failures = 0
        self.verified_token_revocations = 0
        self.child_cleanup_verified = True
        self.child_creation_attempted = False
        self.child_id = ""
        self.child_nicknames: set[str] = set()

    def mark(self, name: str) -> None:
        require(name in CHECK_NAMES, "CHECK_NAME_INVALID")
        self.checks[name] = True

    def api(
        self,
        method: str,
        path: str,
        account: SyntheticAccount | None = None,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        status: int = 200,
    ) -> httpx.Response:
        return require_status(
            self.http.request(
                method,
                API_BASE + path,
                token=account.token if account else "",
                body=body,
                params=params,
            ),
            status,
        )

    def run(self) -> dict[str, Any]:
        try:
            self._run()
            self.stage = "cleanup"
        finally:
            self._cleanup()
        require(self.child_cleanup_verified and self.token_cleanup_failures == 0, "CLEANUP_NOT_VERIFIED")
        require(set(self.checks) == CHECK_NAMES, "ACCEPTANCE_INCOMPLETE")
        self.stage = "complete"
        return self.public_evidence("pass")

    def _run(self) -> None:
        self.admin.preflight()
        self._health()
        self._authenticate_fixtures()
        users = self._identity_capabilities()
        self._parent_profiles(users)
        self._child_age()
        self._ownership()
        self._direct_database_denial()

    def _health(self) -> None:
        self.stage = "health_and_anonymous"
        require(payload(self.api("GET", "/healthz")) == {"status": "ok"})
        require(payload(self.api("GET", "/readyz")) == {"status": "healthy"})
        for path in ("/me", "/capabilities", "/parent-profile", "/children"):
            self.api("GET", path, status=401)
            require_status(self.http.request("GET", API_BASE + path, token="pc02-invalid-synthetic-token"), 401)
        self.mark("health_ready_anonymous_invalid_denial")

    def _authenticate_fixtures(self) -> None:
        self.stage = "synthetic_authentication"
        self.accounts = existing_fixture_accounts(self.admin)
        require(len(self.accounts) == 2, "SYNTHETIC_FIXTURE_COUNT_INVALID")
        require(
            all(
                FIXTURE_NAME_PATTERN.fullmatch(item.username) and UID_PATTERN.fullmatch(item.uid)
                for item in self.accounts
            ),
            "SYNTHETIC_FIXTURE_INVALID",
        )
        require(
            len({item.uid for item in self.accounts}) == len({item.username for item in self.accounts}) == 2,
            "SYNTHETIC_FIXTURE_INVALID",
        )
        self.accounts.sort(key=lambda item: item.username)
        for account in self.accounts:
            reset_fixture_password(self.admin, account)
            login(self.http, account)
        self.mark("two_existing_cloudbase_principals_verified")

    def _identity_capabilities(self) -> list[dict[str, Any]]:
        self.stage = "identity_and_capabilities"
        users = [payload(self.api("GET", "/me", account)) for account in self.accounts]
        for account, user in zip(self.accounts, users):
            require_uuid(user.get("id"))
            require(user["id"] != account.uid)
            require(payload(self.api("GET", "/me", account))["id"] == user["id"])
            require(
                payload(self.api("GET", "/capabilities", account)) == {"child_age_band": True, "parent_profile": True},
                "PC02_FEATURES_UNAVAILABLE",
            )
        require(users[0]["id"] != users[1]["id"])
        self.mark("application_identity_mapping_distinct_stable")
        self.mark("pc02_capabilities_enabled")
        self.require_b_empty(self.accounts[1])
        return users

    def _parent_profiles(self, users: list[dict[str, Any]]) -> None:
        a = self.accounts[0]
        self.stage = "parent_profiles"
        profiles: list[ParentDTO] = []
        for account, user in zip(self.accounts, users):
            initial = parent_dto(self.api("GET", "/parent-profile", account), nullable=True)
            if initial is not None:
                require(initial["id"] not in {user["id"], account.uid})
            saved = parent_dto(
                self.api("PUT", "/parent-profile", account, body={"nickname": SYNTHETIC_PARENT_NICKNAME})
            )
            require(saved["nickname"] == SYNTHETIC_PARENT_NICKNAME)
            require(saved["id"] not in {user["id"], account.uid})
            if initial is not None:
                require(saved["id"] == initial["id"] and saved["created_at"] == initial["created_at"])
            require(parent_dto(self.api("GET", "/parent-profile", account)) == saved)
            again = parent_dto(
                self.api("PUT", "/parent-profile", account, body={"nickname": SYNTHETIC_PARENT_NICKNAME})
            )
            require(again["id"] == saved["id"] and again["created_at"] == saved["created_at"])
            profiles.append(again)
        require(profiles[0]["id"] != profiles[1]["id"] and profiles[0]["nickname"] == profiles[1]["nickname"])
        self.mark("parent_profile_public_dto_boundary")
        self.mark("parent_profile_saved_read_back_stable")
        self.mark("duplicate_parent_nicknames_distinct_ids")
        for extra in (
            {"owner_user_id": users[1]["id"]},
            {"uid": a.uid},
            {"openid": "synthetic-forbidden"},
            {"id": profiles[1]["id"]},
        ):
            self.api("PUT", "/parent-profile", a, body={"nickname": "PC02合成拒绝", **extra}, status=422)
        for account, expected in zip(self.accounts, profiles):
            require(parent_dto(self.api("GET", "/parent-profile", account)) == expected)
        self.mark("client_identity_fields_rejected")

    def _child_age(self) -> None:
        a = self.accounts[0]
        self.stage = "child_age"
        nonce = secrets.token_hex(8)
        nickname, renamed = f"PC02 synthetic child {nonce}", f"PC02 synthetic updated {nonce}"
        self.child_nicknames = {nickname, renamed}
        self.child_creation_attempted = True
        child = payload(self.api("POST", "/children", a, body={"nickname": nickname}, status=201))
        # Keep an identifiable fresh synthetic record reachable for cleanup even
        # when the rest of the creation response violates its public DTO.
        if child.get("nickname") == nickname:
            require_uuid(child.get("id"))
            self.child_id = child["id"]
        require(
            set(child) == CHILD_FIELDS
            and child["nickname"] == nickname
            and child["age_band"] is None
            and child["status"] == "active"
        )
        require_uuid(child["id"])
        path = f"/children/{self.child_id}"
        require(payload(self.api("GET", path, a)) == child)
        with_age = payload(self.api("PATCH", path, a, body={"nickname": nickname, "age_band": "6-8"}))
        require(with_age["age_band"] == "6-8" and payload(self.api("GET", path, a))["age_band"] == "6-8")
        self.mark("optional_child_age_create_read")
        preserved = payload(self.api("PATCH", path, a, body={"nickname": renamed}))
        require(preserved["nickname"] == renamed and preserved["age_band"] == "6-8")
        require(payload(self.api("GET", path, a))["age_band"] == "6-8")
        changed = payload(self.api("PATCH", path, a, body={"nickname": renamed, "age_band": "9-12"}))
        require(changed["age_band"] == "9-12" and payload(self.api("GET", path, a))["age_band"] == "9-12")
        cleared = payload(self.api("PATCH", path, a, body={"nickname": renamed, "age_band": None}))
        require(cleared["age_band"] is None and payload(self.api("GET", path, a))["age_band"] is None)
        self.mark("child_age_omission_update_clear")
        before_invalid = payload(self.api("GET", path, a))
        self.api("PATCH", path, a, body={"nickname": renamed, "age_band": "18-20"}, status=422)
        require(payload(self.api("GET", path, a)) == before_invalid)
        self.mark("invalid_child_age_rejected")

    def _ownership(self) -> None:
        a, b = self.accounts
        path = f"/children/{self.child_id}"
        self.stage = "ownership_and_input_boundaries"
        before_foreign = payload(self.api("GET", path, a))
        self.api("GET", path, b, status=404)
        self.api("PATCH", path, b, body={"nickname": "PC02合成禁止", "age_band": "0-2"}, status=404)
        self.require_b_empty(b)
        require(payload(self.api("GET", path, a)) == before_foreign)
        self.mark("foreign_child_access_denied_b_empty")

    def _direct_database_denial(self) -> None:
        self.stage = "direct_database_denial"
        for account in self.accounts:
            verify_parent_database_denial(self.http, account)
        self.mark("parent_collection_direct_access_denied")

    def require_b_empty(self, account: SyntheticAccount) -> None:
        result = payload(self.api("GET", "/children", account, params={"include_archived": "true", "limit": 1}))
        require(result.get("items") == [] and type(result.get("total")) is int and result["total"] == 0)

    def _cleanup(self) -> None:
        if self.child_creation_attempted:
            self.child_cleanup_verified = False
            if self.child_id and self.accounts and self.accounts[0].token:
                try:
                    a = self.accounts[0]
                    path = f"/children/{self.child_id}"
                    record = payload(self.api("GET", path, a))
                    require(
                        record["id"] == self.child_id
                        and record["nickname"] in self.child_nicknames
                        and record["status"] in {"active", "archived"}
                    )
                    self.api("DELETE", path, a, status=204)
                    archived = payload(self.api("GET", path, a))
                    require(
                        archived["id"] == self.child_id
                        and archived["status"] == "archived"
                        and archived["nickname"] in self.child_nicknames
                    )
                    self.child_cleanup_verified = True
                    self.mark("new_child_archived_verified")
                except Exception:
                    # An ambiguous creation or archive is never resolved by guessing
                    # from a user list or touching historical records.
                    pass
        for account in self.accounts:
            if account.token:
                try:
                    issued = account.token
                    revoke(self.http, account)
                    for path in ("/capabilities", "/parent-profile", "/children"):
                        require_status(self.http.request("GET", API_BASE + path, token=issued), 401)
                    self.verified_token_revocations += 1
                except Exception:
                    self.token_cleanup_failures += 1
        if (
            self.verified_token_revocations == 2
            and self.token_cleanup_failures == 0
            and all(not account.token for account in self.accounts)
        ):
            self.mark("issued_tokens_revoked_private_api_denied")

    def public_evidence(self, status: Literal["pass", "failed"]) -> dict[str, Any]:
        result = {
            "status": status,
            "env_id": ENV_ID,
            "region": REGION,
            "api_base_url": API_BASE,
            "stage": self.stage if self.stage in STAGES else "unknown",
            "checks": {name: True for name in sorted(CHECK_NAMES) if self.checks.get(name) is True},
            "fixture_mode": "reuse",
            "synthetic_users_created": 0,
            "child_cleanup_verified": self.child_cleanup_verified is True,
            "api_token_cleanup_verified": self.verified_token_revocations == 2
            and self.token_cleanup_failures == 0
            and all(not account.token for account in self.accounts),
        }
        for name, value in (
            ("requests", self.http.requests),
            ("rate_limit_retries", self.http.rate_retries),
            ("max_request_latency_ms", self.http.max_latency_ms),
        ):
            if type(value) is int and value >= 0:
                result[name] = value
        if status == "failed":
            result["code"] = "PC02_ACCEPTANCE_FAILED"
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--cloud-write-authorized", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(
            json.dumps(
                {
                    "status": "plan",
                    "env_id": ENV_ID,
                    "region": REGION,
                    "api_base_url": API_BASE,
                    "real_calls": False,
                    "existing_synthetic_users": 2,
                    "synthetic_users_created": 0,
                    "fixture_mode": "reuse",
                    "destructive_operations": [],
                    "requires": ["--apply", "--cloud-write-authorized"],
                    "retained": ["synthetic parent profiles", "archived synthetic child metadata"],
                },
                sort_keys=True,
            )
        )
        return 0
    if not args.cloud_write_authorized:
        print(json.dumps({"status": "blocked", "code": "CLOUD_WRITE_AUTHORIZATION_REQUIRED", "real_calls": False}))
        return 1
    runner = None
    try:
        with httpx.Client(follow_redirects=False, trust_env=False) as client:
            runner = FamilyAcceptance(CloudAdmin(CLI_ENTRY), PrivateHttp(client))
            runner.run()
        print(json.dumps(runner.public_evidence("pass"), sort_keys=True))
        return 0
    except Exception:
        # No exception, response body, account field, token, or password is public.
        result = (
            runner.public_evidence("failed")
            if runner
            else {"status": "failed", "code": "PC02_ACCEPTANCE_FAILED", "stage": "initialization", "checks": {}}
        )
        print(json.dumps(result, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
