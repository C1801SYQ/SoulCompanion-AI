"""PC03 code-only deployment on Fake CLI and private Mock HTTP, never live cloud."""

import base64
from copy import deepcopy
import hashlib
import io
import json
import stat
import zipfile

import httpx
import pytest

from scripts import cloud_community_deploy as deploy
from scripts.cloud_admin import AdminError, ENV_ID, REGION
from scripts.cloud_deploy import FUNCTION, OWNER_MARKER, ROUTE
from scripts.cloud_family_deploy import DOWNLOAD_HOST, UPLOAD_HOST


REQUEST_ID = "12345678-1234-1234-1234-123456789abc"


def package(content: bytes, *, mode=0o755, directory=False, extra=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        if directory:
            entry = zipfile.ZipInfo("soulcompanion_cloud/")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFDIR | 0o755) << 16
            archive.writestr(entry, b"")
        for name, data in {"scf_bootstrap": b"#!/bin/bash\n", "soulcompanion_cloud/app.py": content}.items():
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | (mode if name == "scf_bootstrap" else 0o644)) << 16
            archive.writestr(entry, data)
        if extra:
            archive.writestr(extra, b"unapproved-extra")
    return stream.getvalue()


class FakeAdmin:
    def __init__(self, historical, candidate):
        self.current = historical
        self.candidate = candidate
        self.uploaded = None
        self.calls = []
        self.writes = []
        self.function_exists = True
        self.route_exists = True
        self.route = deepcopy(ROUTE)
        self.bill = {"env_id": ENV_ID, "region": REGION, "package_id": "baas_trial",
                     "overrun": False, "auto_renew": False, "database_id": deploy.DATABASE_ID}
        self.base = {"EnvId": ENV_ID, "Region": REGION, "Status": "NORMAL",
                     "Databases": [{"InstanceId": deploy.DATABASE_ID, "Status": "RUNNING"}]}
        self.detail = {"FunctionName": FUNCTION, "Namespace": ENV_ID, "Description": OWNER_MARKER,
                       "Type": "HTTP", "Runtime": "Python3.11", "MemorySize": 256, "Timeout": 3,
                       "Status": "Active", "Handler": "index.main", "InstallDependency": "FALSE",
                       "Environment": {"Variables": [{"Key": "SYNTHETIC_PRIVATE", "Value": "never-emit-synthetic-value"}]}}
        self.download_url = f"https://{DOWNLOAD_HOST}/synthetic.zip?sign=synthetic-private-download"
        self.remote_hash = None
        self.sign = "synthetic-private-temp-signature"
        self.cos_date = "2026-10-11"
        self.app_id = "1250123456"
        self.ack = {"RequestId": REQUEST_ID}
        self.fail_update = False
        self.after_update = None
        self.after_upload = None
        self.pending_reads = 0

    def preflight(self):
        self.calls.append("preflight")
        return deepcopy(self.bill)

    def api(self, action, body, *, write=False):
        assert write is False and body["EnvId"] == ENV_ID
        self.calls.append(action)
        if action == "DescribeHTTPServiceRoute":
            return {"Domains": [{"Domain": f"{ENV_ID}-123.ap-shanghai.app.tcloudbase.com",
                                 "Routes": [deepcopy(self.route)] if self.route_exists else []}]}
        assert action == "DescribeEnvInfo"
        return {"EnvInfo": {"EnvBaseInfo": deepcopy(self.base), "UserInfo": {"AppId": self.app_id}}}

    def capture(self, args, *, timeout=60):
        self.calls.append(deepcopy(args))
        if args[:2] == ["fn", "list"]:
            return json.dumps({"data": {"Functions": [{"FunctionName": FUNCTION}] if self.function_exists else [],
                                         "TotalCount": int(self.function_exists)}})
        if args[:2] == ["fn", "detail"]:
            if self.writes and self.pending_reads:
                self.pending_reads -= 1
                return json.dumps({"data": {**self.detail, "Status": "Updating"}})
            return json.dumps({"data": self.detail})
        assert args[:2] == ["api", "scf"]
        action = args[2]
        body = json.loads(args[args.index("--body") + 1])
        assert "never-emit-synthetic-value" not in json.dumps(body)
        if action == "GetFunctionAddress":
            assert body == {"FunctionName": FUNCTION, "Namespace": ENV_ID, "Qualifier": "$LATEST"}
            result = {"Url": self.download_url, "CodeSha256": self.remote_hash or deploy.digest(self.current), "RequestId": REQUEST_ID}
        elif action == "GetTempCosInfo":
            assert body == {"ObjectPath": f"{self.app_id}/{ENV_ID}/{FUNCTION}.zip"}
            result = {"Date": self.cos_date, "Sign": self.sign, "RequestId": REQUEST_ID}
        else:
            assert action == "UpdateFunctionCode"
            assert set(body) == {"FunctionName", "Namespace", "InstallDependency", "Publish", "Code"}
            assert body["FunctionName"] == FUNCTION and body["Namespace"] == ENV_ID
            assert body["InstallDependency"] == "FALSE" and body["Publish"] == "FALSE"
            assert set(body["Code"]) == {"CosBucketRegion", "TempCosObjectName"}
            self.writes.append(body)
            if self.fail_update:
                raise AdminError("SYNTHETIC_PRIVATE_FAILURE")
            assert self.uploaded is not None
            self.current = self.uploaded
            if self.after_update:
                self.after_update(self)
            result = self.ack
        return json.dumps({"data": {"Response": result}})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    previous, candidate_bytes = package(b"pc02"), package(b"pc03")
    historical, candidate = tmp_path / "pc02.zip", tmp_path / "pc03.zip"
    historical.write_bytes(previous)
    candidate.write_bytes(candidate_bytes)
    monkeypatch.setattr(deploy, "PC02_SHA256", deploy.digest(previous))
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setattr(deploy, "BACKUPS", tmp_path / ".test-artifacts/cloudbase-pc03/function-backups")
    monkeypatch.setattr(deploy, "APPROVED_PACKAGES", tmp_path / ".test-artifacts/cloudbase-pc03/approved-packages")
    monkeypatch.setattr(deploy, "validate_package", lambda path: {"zip_sha256": deploy.digest(path.read_bytes())})
    admin = FakeAdmin(previous, candidate_bytes)
    contacted = []
    def respond(request):
        contacted.append(request)
        if request.method == "GET":
            assert request.url.host == DOWNLOAD_HOST
            assert "Authorization" not in request.headers and "Cookie" not in request.headers
            return httpx.Response(200, stream=httpx.ByteStream(admin.current))
        assert request.method == "PUT" and request.url.host == UPLOAD_HOST
        assert request.content in (candidate_bytes, previous)
        assert request.headers["Authorization"] == admin.sign
        admin.uploaded = request.content
        if admin.after_upload:
            admin.after_upload(admin)
        return httpx.Response(200, headers={"ETag": '"' + hashlib.md5(request.content, usedforsecurity=False).hexdigest() + '"'})
    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False, trust_env=False) as client:
        yield candidate, historical, admin, deploy.ZipTransport(admin, client), contacted


def apply(setup, **kwargs):
    candidate, historical, admin, transport, _ = setup
    return deploy.apply_deployment(admin, transport, candidate, historical, cloud_write_authorized=True, **kwargs)


def test_production_defaults_pin_pc02_and_keep_separate_candidate_artifacts():
    assert deploy.PC02_SHA256 == "81726829c4384d2474509cf382a5b38abd26c0ee0a265a32bcdf0df00956b6b6"
    assert "cloudbase-pc02" in str(deploy.PC02_PACKAGE) and "cloudbase-pc03" in str(deploy.PACKAGE)
    assert deploy.PC02_PACKAGE != deploy.PACKAGE


def test_forward_uploads_exact_bytes_preserves_private_config_and_only_updates_code(setup):
    candidate, _, admin, _, requests = setup
    configuration, historical = deepcopy(admin.detail), setup[1].read_bytes()
    result = apply(setup)
    assert result["status"] == "code_verified" and result["configuration_unchanged"]
    assert result["zip_sha256"] == deploy.digest(candidate.read_bytes())
    assert result["remote_code_sha256"] == deploy.digest(admin.current)
    assert result["new_resources"] == 0 and result["schema_marker_changes"] == []
    assert result["real_cloud_api_acceptance"] == "NOT TESTED"
    assert admin.current == candidate.read_bytes() and admin.detail == configuration
    assert setup[1].read_bytes() == historical and len(admin.writes) == 1
    assert [request.method for request in requests] == ["GET", "PUT", "GET"]
    for secret in (admin.sign, "synthetic-private-download", "never-emit-synthetic-value"):
        assert secret not in json.dumps(result)
    assert len(list(deploy.BACKUPS.glob("*.zip"))) == 1


def test_repeated_apply_and_rollback_are_noop_when_desired_members_already_current(setup):
    admin = setup[2]
    admin.current = admin.candidate
    assert apply(setup)["status"] == "already_verified"
    assert not admin.writes and [request.method for request in setup[4]] == ["GET"]
    admin.current = setup[1].read_bytes()
    assert apply(setup, rollback=True)["status"] == "already_verified"
    assert not admin.writes


def test_explicit_rollback_restores_pinned_pc02_and_does_not_write_schema_or_data(setup):
    candidate, historical, admin, _, _ = setup
    admin.current = candidate.read_bytes()
    before = deepcopy(admin.detail)
    result = apply(setup, rollback=True)
    assert result["status"] == "code_verified" and result["rollback"] is True
    assert admin.current == historical.read_bytes() and admin.detail == before
    assert result["schema_marker_changes"] == [] and len(admin.writes) == 1
    assert all(call not in {"CreateTable", "ModifyDatabaseACL", "UpdateTable"} for call in admin.calls if isinstance(call, str))


@pytest.mark.parametrize("authorized", [False, None, 1, "true"])
def test_authorization_is_explicit_boolean_and_checked_before_any_cloud_read(setup, authorized):
    candidate, historical, admin, transport, requests = setup
    with pytest.raises(AdminError, match="CLOUD_WRITE_AUTHORIZATION_REQUIRED"):
        deploy.apply_deployment(admin, transport, candidate, historical, cloud_write_authorized=authorized)
    assert not admin.calls and not requests


def test_offline_plan_and_cli_double_gate_never_construct_admin(setup, monkeypatch, capsys):
    candidate, historical, *_ = setup
    monkeypatch.setattr(deploy, "CloudAdmin", lambda: pytest.fail("No administrator can be constructed offline."))
    assert deploy.main(["--package", str(candidate), "--pc02-package", str(historical)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["real_calls"] is False and result["operation"] == "update_pc03_code"
    assert result["billing_guards"] == {"package_id": "baas_trial", "overrun": False, "auto_renew": False}
    assert result["identity_changes"] == result["schema_marker_changes"] == []
    assert "not a lifetime-free guarantee" in result["cost"]
    assert "separately authorized" in result["marker_disabling"]
    assert deploy.main(["--apply"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "CLOUD_WRITE_AUTHORIZATION_REQUIRED"
    assert deploy.main(["--rollback", "--package", str(candidate), "--pc02-package", str(historical)]) == 0
    assert json.loads(capsys.readouterr().out)["operation"] == "restore_pc02_code"


@pytest.mark.parametrize("field,value", [("env_id", "wrong"), ("region", "ap-beijing"),
    ("package_id", "paid"), ("overrun", True), ("auto_renew", True), ("database_id", "wrong")])
def test_wrong_billing_or_database_never_uploads(setup, field, value):
    setup[2].bill[field] = value
    with pytest.raises(AdminError):
        apply(setup)
    assert not setup[2].writes and not setup[4]


@pytest.mark.parametrize("field,value", [("EnvId", "wrong"), ("Region", "ap-beijing"), ("Status", "DELETED"),
    ("Databases", []), ("Databases", [{"InstanceId": "foreign", "Status": "RUNNING"}]),
    ("Databases", [{"InstanceId": deploy.DATABASE_ID, "Status": "STOPPED"}]),
    ("Databases", [{"InstanceId": deploy.DATABASE_ID, "Status": "RUNNING"}] * 2), ("Databases", None)])
def test_fresh_actual_environment_metadata_not_just_constant_preflight_label(setup, field, value):
    setup[2].base[field] = value
    with pytest.raises(AdminError, match="COMMUNITY_DEPLOY_TARGET_UNVERIFIED"):
        apply(setup)
    assert not setup[2].writes and not setup[4]


@pytest.mark.parametrize("field,value", [("Description", "foreign"), ("FunctionName", "foreign"),
    ("Namespace", "wrong"), ("Type", "Event"), ("Runtime", "Nodejs"),
    ("MemorySize", 512), ("Timeout", 10), ("Status", "Updating")])
def test_configuration_and_owner_must_be_existing_phase04_resources(setup, field, value):
    setup[2].detail[field] = value
    with pytest.raises(AdminError):
        apply(setup)
    assert not setup[2].writes and not setup[4]


@pytest.mark.parametrize("missing", ["function_exists", "route_exists"])
def test_missing_resources_are_never_created(setup, missing):
    setattr(setup[2], missing, False)
    with pytest.raises(AdminError):
        apply(setup)
    assert not setup[2].writes and not setup[4]


def test_unapproved_gateway_auth_or_limits_do_not_get_changed(setup):
    setup[2].route["EnableAuth"] = True
    with pytest.raises(AdminError):
        apply(setup)
    assert not setup[2].writes


@pytest.mark.parametrize("current", [b"phase04", b"unknown", b"pc02-with-new-file"])
def test_phase04_and_unknown_remote_code_cannot_be_adopted(setup, current):
    setup[2].current = package(current)
    with pytest.raises(AdminError, match="CURRENT_CODE_NOT_OWNED"):
        apply(setup)
    assert not setup[2].writes


def test_pc02_remote_recompression_verified_member_by_member(setup):
    setup[2].current = package(b"pc02", mode=0o777, directory=True)
    assert apply(setup)["status"] == "code_verified"


@pytest.mark.parametrize("mode", [0o644, 0o666])
def test_remote_bootstrap_must_remain_executable(setup, mode):
    setup[2].current = package(b"pc02", mode=mode)
    with pytest.raises(AdminError, match="ZIP_CONTENT_UNVERIFIED"):
        apply(setup)
    assert not setup[2].writes


@pytest.mark.parametrize("extra", ["../secret", "C:/secret", ".env", "tests/secret.py", "orphan/", "soulcompanion_cloud/../bad/"])
def test_unsafe_or_unowned_members_stop_before_update(setup, extra):
    setup[2].current = package(b"pc02", extra=extra)
    with pytest.raises(AdminError, match="ZIP_CONTENT_UNVERIFIED"):
        apply(setup)
    assert not setup[2].writes


def test_historical_pc02_checksum_cannot_be_changed_or_replaced(setup):
    setup[1].write_bytes(package(b"tampered-pc02"))
    with pytest.raises(AdminError, match="PC02_PACKAGE_CHECKSUM_MISMATCH"):
        apply(setup)
    assert not setup[2].calls


def test_identical_candidate_and_baseline_or_same_path_is_not_a_pc03_package(setup):
    setup[0].write_bytes(setup[1].read_bytes())
    with pytest.raises(AdminError, match="CANDIDATE_EQUALS_PC02_BASELINE"):
        apply(setup)
    with pytest.raises(AdminError, match="CANDIDATE_AND_HISTORY_MUST_DIFFER"):
        deploy.packages(setup[1], setup[1])


def test_local_bootstrap_exact_0755_required_even_if_member_validation_accepts_777(setup):
    setup[0].write_bytes(package(b"pc03", mode=0o777))
    with pytest.raises(AdminError, match="LOCAL_BOOTSTRAP_MODE_UNVERIFIED"):
        apply(setup)
    assert not setup[2].calls


def test_local_source_or_package_changed_since_initial_validation_blocks_update(setup, monkeypatch):
    calls = 0
    def validation(path):
        nonlocal calls
        calls += 1
        return {"zip_sha256": deploy.digest(path.read_bytes()) if calls == 1 else "0" * 64}
    monkeypatch.setattr(deploy, "validate_package", validation)
    with pytest.raises(AdminError, match="PACKAGE_CHANGED_AFTER_VALIDATION"):
        apply(setup)
    assert not setup[2].writes and all(request.method != "PUT" for request in setup[4])


def test_remote_configuration_race_after_upload_blocks_code_write(setup):
    setup[2].after_upload = lambda admin: admin.detail.update(Handler="foreign.main")
    with pytest.raises(AdminError, match="FUNCTION_CONFIGURATION_CHANGED"):
        apply(setup)
    assert not setup[2].writes and [request.method for request in setup[4]] == ["GET", "PUT"]


def test_remote_code_race_at_final_prewrite_check_blocks_update(setup):
    admin = setup[2]
    original, count = admin.capture, 0
    def capture(args, **kwargs):
        nonlocal count
        if args[:3] == ["api", "scf", "GetFunctionAddress"]:
            count += 1
            if count == 3:
                admin.current = package(b"concurrent-unknown")
        return original(args, **kwargs)
    admin.capture = capture
    with pytest.raises(AdminError, match="CURRENT_CODE_CHANGED"):
        apply(setup)
    assert not admin.writes


def test_transport_cannot_be_swapped_for_different_administrator(setup):
    setup[3].admin = FakeAdmin(b"different", b"different")
    with pytest.raises(AdminError, match="DEPLOYMENT_TRANSPORT_MISMATCH"):
        apply(setup)
    assert not setup[2].calls


def test_backup_failure_aborts_without_overwriting_foreign_files(setup):
    deploy.BACKUPS.mkdir(parents=True)
    path = deploy.BACKUPS / f"{deploy.digest(setup[2].current)}.zip"
    path.write_bytes(b"foreign-file")
    with pytest.raises(AdminError, match="PRIVATE_BACKUP_NOT_RETAINED"):
        apply(setup)
    assert path.read_bytes() == b"foreign-file"
    assert not setup[2].writes and all(request.method != "PUT" for request in setup[4])


@pytest.mark.parametrize("field,value", [("MemorySize", 512), ("Handler", "changed.main"),
    ("Environment", {"Variables": [{"Key": "PRIVATE", "Value": "changed-synthetic-secret"}]})])
def test_post_update_config_change_is_failed_without_exposing_private_values(setup, field, value):
    setup[2].after_update = lambda admin: admin.detail.update({field: value})
    with pytest.raises(AdminError) as error:
        apply(setup)
    assert "changed-synthetic-secret" not in str(error.value)
    assert len(setup[2].writes) == 1


def test_update_failure_and_bad_sdk_ack_do_not_claim_success_or_retry_write(setup):
    setup[2].fail_update = True
    with pytest.raises(AdminError, match="CODE_UPDATE_FAILED"):
        apply(setup)
    assert len(setup[2].writes) == 1 and len(list(deploy.BACKUPS.glob("*.zip"))) == 1
    setup[2].fail_update = False
    setup[2].ack = {"message": "success"}
    with pytest.raises(AdminError, match="CODE_UPDATE_NOT_CONFIRMED"):
        apply(setup)
    assert len(setup[2].writes) == 2
    assert apply(setup)["status"] == "already_verified"
    assert len(setup[2].writes) == 2


def test_postwrite_wrong_code_is_bounded_failure_and_never_retries_code_write(setup):
    old = setup[2].current
    setup[2].after_update = lambda admin: setattr(admin, "current", old)
    waits = []
    with pytest.raises(AdminError, match="UPDATED_CODE_NOT_VERIFIED"):
        apply(setup, sleep=waits.append)
    assert waits == [3, 3, 3, 3] and len(setup[2].writes) == 1


def test_pending_official_runtime_status_waits_bounded_then_verifies(setup):
    setup[2].pending_reads = 2
    waits = []
    assert apply(setup, sleep=waits.append)["status"] == "code_verified"
    assert waits == [3, 3]


@pytest.mark.parametrize("url", ["https://example.com/private", "http://" + DOWNLOAD_HOST + "/x",
    "https://user@" + DOWNLOAD_HOST + "/x", "https://" + DOWNLOAD_HOST + ":444/x",
    "https://" + DOWNLOAD_HOST + "/x#private", "https://" + DOWNLOAD_HOST + "/x\r\n"])
def test_signed_download_target_remains_strict_and_never_leaks(setup, url):
    setup[2].download_url = url
    with pytest.raises(AdminError, match="UNAPPROVED_DOWNLOAD_TARGET"):
        apply(setup)
    assert not setup[4] and not setup[2].writes


def test_remote_digest_must_match_download_bytes_and_supports_official_base64(setup):
    setup[2].remote_hash = "0" * 64
    with pytest.raises(AdminError, match="REMOTE_CODE_CHECKSUM_MISMATCH"):
        apply(setup)
    assert not setup[2].writes
    setup[2].remote_hash = base64.b64encode(hashlib.sha256(setup[2].current).digest()).decode()
    assert setup[3].download()[0] == setup[2].current


@pytest.mark.parametrize("status", [302, 403])
def test_upload_redirect_failure_never_calls_update(setup, status):
    admin = setup[2]
    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, stream=httpx.ByteStream(admin.current))
        return httpx.Response(status, headers={"Location": "https://foreign.example/private"})
    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
        transport = deploy.ZipTransport(admin, client)
        with pytest.raises(AdminError, match="PRIVATE_UPLOAD_NOT_CONFIRMED"):
            deploy.apply_deployment(admin, transport, setup[0], setup[1], cloud_write_authorized=True)
    assert not admin.writes


def test_raw_sdk_exception_and_unknown_cli_error_never_print_secrets(setup, monkeypatch, capsys):
    candidate, historical, *_ = setup
    monkeypatch.setattr(deploy, "CloudAdmin", lambda: setup[2])
    def unsafe(*args, **kwargs):
        raise AdminError("synthetic-secret-token https://example.com/private")
    monkeypatch.setattr(deploy, "apply_deployment", unsafe)
    assert deploy.main(["--apply", "--cloud-write-authorized", "--package", str(candidate), "--pc02-package", str(historical)]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["code"] == "COMMUNITY_CODE_DEPLOYMENT_FAILED"
    assert "synthetic-secret-token" not in output and "https://" not in output


def test_rollback_survives_changed_source_validation_after_verified_forward(setup, monkeypatch):
    assert apply(setup)["status"] == "code_verified"
    assert len(list(deploy.APPROVED_PACKAGES.glob("*.zip"))) == 1
    def stale_candidate(path):
        raise AdminError("PACKAGE_NOT_DEPLOYABLE_OR_STALE")
    monkeypatch.setattr(deploy, "validate_package", stale_candidate)
    result = apply(setup, rollback=True)
    assert result["status"] == "code_verified" and setup[2].current == setup[1].read_bytes()
    assert len(setup[2].writes) == 2


def test_missing_or_replaced_candidate_cannot_block_fixed_pc02_rollback(setup, monkeypatch):
    assert apply(setup)["status"] == "code_verified"
    # Simulate loss of the mutable candidate path; the frozen source-approved
    # archive is independent of the working tree and survives it.
    monkeypatch.setattr(deploy, "validate_package", lambda path: pytest.fail("Rollback must not validate current source."))
    missing = setup[0].parent / "missing-candidate.zip"
    result = deploy.apply_deployment(setup[2], setup[3], missing, setup[1], cloud_write_authorized=True, rollback=True)
    assert result["status"] == "code_verified" and result["rollback"]
    assert setup[2].current == setup[1].read_bytes()
    assert deploy.plan(missing, setup[1], rollback=True)["zip_sha256"] == deploy.digest(setup[1].read_bytes())


def test_rollback_of_existing_pc02_needs_no_pc03_candidate_or_frozen_archive(setup, monkeypatch):
    monkeypatch.setattr(deploy, "validate_package", lambda path: pytest.fail("No PC03 candidate needed for PC02 no-op."))
    result = apply(setup, rollback=True)
    assert result["status"] == "already_verified" and not setup[2].writes


def test_unknown_current_code_remains_rejected_even_with_approved_frozen_pc03(setup):
    assert apply(setup)["status"] == "code_verified"
    setup[2].current = package(b"foreign-code")
    with pytest.raises(AdminError, match="CURRENT_CODE_NOT_OWNED"):
        apply(setup, rollback=True)
    assert len(setup[2].writes) == 1


def test_tampered_frozen_candidate_never_grants_rollback_ownership(setup):
    assert apply(setup)["status"] == "code_verified"
    frozen = next(deploy.APPROVED_PACKAGES.glob("*.zip"))
    frozen.write_bytes(package(b"forged-owned-proof"))
    with pytest.raises(AdminError, match="APPROVED_PACKAGE_UNVERIFIED"):
        apply(setup, rollback=True)
    assert len(setup[2].writes) == 1


def test_forward_hotfix_accepts_exact_previously_frozen_pc03_members(setup):
    assert apply(setup)["status"] == "code_verified"
    candidate, historical, admin, *_ = setup
    prior_code = admin.current
    hotfix = package(b"pc03-reviewed-hotfix")
    candidate.write_bytes(hotfix)
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "GET":
            assert request.url.host == DOWNLOAD_HOST
            return httpx.Response(200, stream=httpx.ByteStream(admin.current))
        assert request.method == "PUT" and request.url.host == UPLOAD_HOST
        assert request.content == hotfix and request.headers["Authorization"] == admin.sign
        admin.uploaded = request.content
        return httpx.Response(200, headers={"ETag": '"' + hashlib.md5(hotfix, usedforsecurity=False).hexdigest() + '"'})

    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False, trust_env=False) as client:
        transport = deploy.ZipTransport(admin, client)
        result = deploy.apply_deployment(admin, transport, candidate, historical, cloud_write_authorized=True)
        assert result["status"] == "code_verified" and admin.current == hotfix
        assert deploy.apply_deployment(admin, transport, candidate, historical, cloud_write_authorized=True)["status"] == "already_verified"
    assert prior_code != hotfix and len(admin.writes) == 2
    assert [request.method for request in requests] == ["GET", "PUT", "GET", "GET"]
    assert len(list(deploy.APPROVED_PACKAGES.glob("*.zip"))) == 2


def test_forward_hotfix_rejects_unknown_remote_despite_frozen_pc03_evidence(setup):
    assert apply(setup)["status"] == "code_verified"
    setup[0].write_bytes(package(b"pc03-reviewed-hotfix"))
    setup[2].current = package(b"pc03-unreviewed-code")
    with pytest.raises(AdminError, match="CURRENT_CODE_NOT_OWNED"):
        apply(setup)
    assert len(setup[2].writes) == 1
