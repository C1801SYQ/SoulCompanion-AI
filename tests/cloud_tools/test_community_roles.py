"""Protected role administration with fake principals and no cloud writes."""

import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from scripts import cloud_community_roles as roles
from cloud.api.soulcompanion_cloud.errors import CloudError, unavailable
from cloud.api.soulcompanion_cloud.community.repository import InMemoryCommunityRepository
from cloud.api.soulcompanion_cloud.community.service import role_binding_id, validate_role


PRINCIPAL = str(uuid4())
AdminError, ENV_ID, REGION = roles.AdminError, roles.ENV_ID, roles.REGION


class FakeEnvironment:
    def __init__(self, store=None):
        self.store = store or InMemoryCommunityRepository()
        self.user = {"_id": PRINCIPAL, "id": PRINCIPAL, "status": "active"}
        self.audit = {"env_id": ENV_ID, "region": REGION, "package_id": "baas_trial",
                      "overrun": False, "auto_renew": False, "database_id": roles.DATABASE_ID}
        self.environment_info = {"EnvInfo": {"EnvBaseInfo": {
            "EnvId": ENV_ID, "Region": REGION, "Status": "NORMAL",
            "Databases": [{"InstanceId": roles.DATABASE_ID, "Status": "RUNNING"}],
        }}}
        self.reads = 0
        self.preflights = 0
        self.environment_reads = 0

    def preflight(self):
        self.preflights += 1
        return deepcopy(self.audit)

    async def lookup(self, principal):
        self.reads += 1
        assert principal == PRINCIPAL
        return deepcopy(self.user)

    def actual_environment(self):
        self.environment_reads += 1
        return deepcopy(self.environment_info)

    def manager(self):
        return roles.RoleManager(self.store, self.lookup, self.preflight, self.actual_environment)


def change(env, action="grant", key="synthetic-management-key", reason="合成运营角色验收", **kwargs):
    return asyncio.run(env.manager().change(PRINCIPAL, action, reason, key, cloud_write_authorized=True, **kwargs))


def test_offline_plan_never_instantiates_admin_or_reads_credentials(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline plan must not use cloud credentials or admin")
    monkeypatch.setattr(roles, "CloudAdmin", forbidden)
    import cloud_admin
    monkeypatch.setattr(cloud_admin, "load_private_environment", forbidden)
    assert roles.main([]) == 0
    output = capsys.readouterr().out
    assert '"cloud_writes": false' in output and PRINCIPAL not in output


def test_missing_authorization_fails_before_any_cloud_or_user_access():
    env = FakeEnvironment()
    with pytest.raises(AdminError, match="PC03_CLOUD_WRITE_AUTHORIZATION_REQUIRED"):
        asyncio.run(env.manager().change(PRINCIPAL, "grant", "合成验收", "synthetic-key"))
    assert env.reads == env.preflights == env.environment_reads == 0 and not env.store.records["role_bindings"]
    with pytest.raises(AdminError, match="PC03_CLOUD_WRITE_AUTHORIZATION_REQUIRED"):
        roles.main(["--apply"])


@pytest.mark.parametrize("field,value", [
    ("env_id", "foreign-env"), ("region", "ap-other"), ("package_id", "paid-package"),
    ("overrun", True), ("overrun", 0), ("auto_renew", True), ("auto_renew", 0),
    ("database_id", ""), ("database_id", "foreign-db"),
])
def test_wrong_target_or_billing_refuses_role_write(field, value):
    env = FakeEnvironment()
    env.audit[field] = value
    with pytest.raises(AdminError, match="ROLE_PREFLIGHT_NOT_VERIFIED"):
        change(env)
    assert env.reads == 0 and not env.store.records["role_bindings"]


@pytest.mark.parametrize("field,value", [
    ("EnvId", "foreign-environment"), ("EnvId", None),
    ("Region", "ap-guangzhou"), ("Region", None),
    ("Status", "SUSPENDED"), ("Status", None),
    ("Databases", None), ("Databases", {}), ("Databases", []),
    ("Databases", [None]), ("Databases", [{}]),
    ("Databases", [{"InstanceId": roles.DATABASE_ID}]),
    ("Databases", [{"InstanceId": "foreign-db", "Status": "RUNNING"}]),
    ("Databases", [{"InstanceId": roles.DATABASE_ID, "Status": "STOPPED"}]),
    ("Databases", [{"InstanceId": roles.DATABASE_ID, "Status": "RUNNING"}] * 2),
])
def test_actual_region_environment_and_database_block_role_writes(field, value):
    env = FakeEnvironment()
    env.environment_info["EnvInfo"]["EnvBaseInfo"][field] = value
    with pytest.raises(AdminError, match="ROLE_PREFLIGHT_NOT_VERIFIED"):
        change(env)
    assert env.environment_reads == 1 and env.reads == 0
    assert not env.store.records["role_bindings"]
    assert all(not records for records in env.store.records.values())


@pytest.mark.parametrize("response", [None, [], {}, {"EnvInfo": None}, {"EnvInfo": []},
    {"EnvInfo": {}}, {"EnvInfo": {"EnvBaseInfo": None}}, {"EnvInfo": {"EnvBaseInfo": []}}])
def test_actual_environment_missing_structure_cannot_grant_role(response):
    env = FakeEnvironment()
    env.environment_info = response
    with pytest.raises(AdminError, match="ROLE_PREFLIGHT_NOT_VERIFIED"):
        change(env)
    assert env.reads == 0 and not env.store.records["role_bindings"]
    assert all(not records for records in env.store.records.values())


@pytest.mark.parametrize("user", [None, {}, {"id": PRINCIPAL, "status": "active"},
    {"_id": PRINCIPAL, "id": str(uuid4()), "status": "active"},
    {"_id": PRINCIPAL, "id": PRINCIPAL, "status": "disabled"}])
def test_role_only_binds_an_existing_active_verified_application_principal(user):
    env = FakeEnvironment()
    env.user = user
    with pytest.raises(AdminError, match="ACTIVE_APPLICATION_USER_REQUIRED"):
        change(env)
    assert not env.store.records["role_bindings"]


def test_unready_community_cannot_grant_a_role():
    env = FakeEnvironment(InMemoryCommunityRepository(enabled=False))
    with pytest.raises(AdminError, match="COMMUNITY_SCHEMA_NOT_READY"):
        change(env)
    assert env.reads == 0 and not env.store.records["role_bindings"]


def test_grant_revoke_and_replay_are_audited_and_report_current_state():
    env = FakeEnvironment()
    first = change(env)
    identifier = role_binding_id(PRINCIPAL)
    assert first["role_status"] == "active" and first["action_applied"] is True
    original = deepcopy(env.store.records["role_bindings"][identifier])
    assert validate_role(original) == original
    replay = change(env)
    assert not replay["changed"] and replay["action_applied"]
    assert env.store.records["role_bindings"][identifier] == original
    revoked = change(env, "revoke", "synthetic-revoke-key")
    assert revoked["role_status"] == "revoked" and revoked["row_version"] == 2
    historical = change(env)
    assert historical["role_status"] == "revoked" and historical["action_applied"]
    current = env.store.records["role_bindings"][identifier]
    assert current["audit"][0] == original["audit"][0]
    assert len(current["audit"]) == 2 and validate_role(current)
    assert all(entry["actor_id"] == "cloud-admin-cli" for entry in current["audit"])


def test_existing_same_state_is_noop_without_fabricating_audit_action():
    env = FakeEnvironment()
    change(env)
    before = deepcopy(env.store.records["role_bindings"])
    result = change(env, key="another-management-key")
    assert result["changed"] is False and result["action_applied"] is False
    assert env.store.records["role_bindings"] == before


def test_same_action_key_with_different_reason_conflicts():
    env = FakeEnvironment()
    change(env)
    before = deepcopy(env.store.records["role_bindings"])
    with pytest.raises(AdminError, match="ROLE_ACTION_INPUT_CONFLICT"):
        change(env, reason="不同合成理由")
    assert env.store.records["role_bindings"] == before


@pytest.mark.parametrize("user", [None, {"_id": PRINCIPAL, "id": PRINCIPAL, "status": "disabled"}])
def test_revoke_remains_available_for_disabled_or_missing_application_user(user):
    env = FakeEnvironment()
    change(env)
    env.user = user
    reads = env.reads
    result = change(env, "revoke", "synthetic-disabled-user-revoke")
    assert result["role_status"] == "revoked" and result["action_applied"] is True
    assert env.reads == reads
    assert validate_role(env.store.records["role_bindings"][role_binding_id(PRINCIPAL)])


def test_revoking_absent_role_is_noop_and_does_not_create_a_record():
    env = FakeEnvironment()
    assert change(env, "revoke")["role_status"] == "absent"
    assert not env.store.records["role_bindings"]


def test_last_reserved_role_audit_slot_allows_revocation_then_rejects_regrant():
    env = FakeEnvironment()
    for index in range(31):
        change(env, "grant" if index % 2 == 0 else "revoke", f"synthetic-role-{index}")
    assert next(iter(env.store.records["role_bindings"].values()))["status"] == "active"
    assert change(env, "revoke", "synthetic-last-revoke")["row_version"] == 32
    before = deepcopy(env.store.records["role_bindings"])
    with pytest.raises(AdminError, match="ROLE_AUDIT_CAPACITY_EXCEEDED"):
        change(env, "grant", "synthetic-excess-grant")
    assert env.store.records["role_bindings"] == before


def test_cas_conflict_preserves_current_role_and_history():
    class ConflictStore(InMemoryCommunityRepository):
        async def cas(self, *args, **kwargs):
            return False
    env = FakeEnvironment(ConflictStore())
    change(env)
    before = deepcopy(env.store.records["role_bindings"])
    with pytest.raises(AdminError, match="ROLE_ACTION_CONFLICT"):
        change(env, "revoke", "synthetic-revoke")
    assert env.store.records["role_bindings"] == before


def test_committed_revoke_with_lost_ack_returns_failure_then_same_key_recovers():
    class LostAckStore(InMemoryCommunityRepository):
        lose_once = True
        async def cas(self, *args, **kwargs):
            result = await super().cas(*args, **kwargs)
            if self.lose_once:
                self.lose_once = False
                raise unavailable()
            return result
    env = FakeEnvironment(LostAckStore())
    change(env)
    with pytest.raises(CloudError) as error:
        change(env, "revoke", "synthetic-revoke")
    assert error.value.status == 503
    recovered = change(env, "revoke", "synthetic-revoke")
    assert recovered["role_status"] == "revoked" and recovered["action_applied"] is True
    assert recovered["row_version"] == 2


@pytest.mark.parametrize("principal,action,reason,key", [
    ("raw-openid", "grant", "合成理由", "key"), (PRINCIPAL, "admin", "合成理由", "key"),
    (PRINCIPAL, "grant", "", "key"), (PRINCIPAL, "grant", "x" * 201, "key"),
    (PRINCIPAL, "grant", "<script>x</script>", "key"), (PRINCIPAL, "grant", "合成理由", "bad key"),
])
def test_invalid_role_input_never_writes(principal, action, reason, key):
    env = FakeEnvironment()
    with pytest.raises(AdminError, match="ROLE_INPUT_INVALID"):
        asyncio.run(env.manager().change(principal, action, reason, key, cloud_write_authorized=True))
    assert not env.store.records["role_bindings"]
