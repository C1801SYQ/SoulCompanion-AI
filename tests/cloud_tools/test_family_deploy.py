"""PC02 deployment keeps verified ZIP bytes and changes only function code."""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import stat
import zipfile

import httpx
import pytest

from scripts import cloud_family_deploy as deploy
from scripts.cloud_admin import AdminError, ENV_ID, REGION
from scripts.cloud_deploy import FUNCTION, OWNER_MARKER, ROUTE


REQUEST_ID = "12345678-1234-1234-1234-123456789abc"


def package(content: bytes, *, mode: int = 0o755, extra: str | None = None, directories: bool = False) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        if directories:
            info = zipfile.ZipInfo("soulcompanion_cloud/")
            info.create_system = 3
            info.external_attr = (stat.S_IFDIR | 0o755) << 16
            archive.writestr(info, b"")
        for name, value in {"scf_bootstrap": b"#!/bin/bash\n", "soulcompanion_cloud/app.py": content}.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | (mode if name == "scf_bootstrap" else 0o644)) << 16
            archive.writestr(info, value)
        if extra:
            archive.writestr(extra, b"unexpected")
    return stream.getvalue()


class FakeAdmin:
    def __init__(self, old: bytes, forward: bytes):
        self.current = old
        self.forward = forward
        self.calls = []
        self.writes = []
        self.function_exists = True
        self.route_exists = True
        self.bill = {"env_id": ENV_ID, "region": REGION, "package_id": "baas_trial",
                     "overrun": False, "auto_renew": False, "database_id": deploy.DATABASE_ID}
        self.detail = {"FunctionName": FUNCTION, "Namespace": ENV_ID, "Description": OWNER_MARKER,
                       "Type": "HTTP", "Runtime": "Python3.11", "MemorySize": 256, "Timeout": 3,
                       "Status": "Active", "Handler": "index.main", "InstallDependency": "FALSE",
                       "Environment": {"Variables": [{"Key": "PRIVATE", "Value": "never-print-me"}]}}
        self.route = deepcopy(ROUTE)
        self.download_url = f"https://{deploy.DOWNLOAD_HOST}/code.zip?sign=private-download"
        self.remote_hash = None
        self.sign = "private-temp-signature"
        self.date = "2026-10-10"
        self.after_write = None
        self.fail_update = False
        self.ack = {"RequestId": REQUEST_ID}
        self.env_region = REGION
        self.app_id = "1250123456"
        self.pending_reads = 0

    def preflight(self):
        self.calls.append("preflight")
        return deepcopy(self.bill)

    def api(self, action, body, *, write=False):
        assert write is False
        self.calls.append(action)
        if action == "DescribeHTTPServiceRoute":
            return {"Domains": [{"Domain": f"{ENV_ID}-123.ap-shanghai.app.tcloudbase.com",
                                 "Routes": [deepcopy(self.route)] if self.route_exists else []}]}
        assert action == "DescribeEnvInfo"
        return {"EnvInfo": {"EnvBaseInfo": {"EnvId": ENV_ID, "Region": self.env_region,
                                              "Status": "NORMAL"},
                            "UserInfo": {"AppId": self.app_id}}}

    def capture(self, args, *, timeout=60):
        self.calls.append(args)
        if args[:2] == ["fn", "list"]:
            return json.dumps({"data": {"Functions": [{"FunctionName": FUNCTION}] if self.function_exists else [],
                                         "TotalCount": int(self.function_exists)}})
        if args[:2] == ["fn", "detail"]:
            if self.writes and self.pending_reads:
                self.pending_reads -= 1
                return json.dumps({"data": {**deepcopy(self.detail), "Status": "Updating"}})
            return json.dumps({"data": deepcopy(self.detail)})
        assert args[:2] == ["api", "scf"]
        action = args[2]
        body = json.loads(args[args.index("--body") + 1])
        assert "private" not in json.dumps(body)
        if action == "GetFunctionAddress":
            assert body == {"FunctionName": FUNCTION, "Namespace": ENV_ID, "Qualifier": "$LATEST"}
            response = {"Url": self.download_url,
                        "CodeSha256": self.remote_hash or hashlib.sha256(self.current).hexdigest(),
                        "RequestId": REQUEST_ID}
        elif action == "GetTempCosInfo":
            assert body == {"ObjectPath": f"{self.app_id}/{ENV_ID}/{FUNCTION}.zip"}
            response = {"Date": self.date, "Sign": self.sign, "RequestId": REQUEST_ID}
        else:
            assert action == "UpdateFunctionCode"
            self.writes.append(body)
            assert set(body) == {"FunctionName", "Namespace", "InstallDependency", "Publish", "Code"}
            assert body["InstallDependency"] == "FALSE" and body["Publish"] == "FALSE"
            if self.fail_update:
                raise AdminError("EXAMPLE_UPSTREAM_FAILURE")
            self.current = self.forward
            if self.after_write:
                self.after_write(self)
            response = self.ack
        return json.dumps({"data": {"Response": response}})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    old, forward = package(b"phase04"), package(b"pc02")
    historic = tmp_path / "phase04.zip"
    candidate = tmp_path / "pc02.zip"
    historic.write_bytes(old)
    candidate.write_bytes(forward)
    monkeypatch.setattr(deploy, "PHASE04_SHA256", hashlib.sha256(old).hexdigest())
    monkeypatch.setattr(deploy, "validate_package", lambda p: {
        "zip_sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "package_bytes": p.stat().st_size})
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setattr(deploy, "BACKUPS", tmp_path / ".test-artifacts/backups")
    admin = FakeAdmin(old, forward)
    contacted = []

    def respond(request):
        contacted.append(request)
        if request.method == "GET":
            assert request.url.host == deploy.DOWNLOAD_HOST
            assert "Authorization" not in request.headers
            return httpx.Response(200, stream=httpx.ByteStream(admin.current))
        assert request.method == "PUT"
        assert request.url.host == deploy.UPLOAD_HOST
        assert request.content == admin.forward
        assert request.headers["Authorization"] == admin.sign
        assert request.headers["Content-MD5"]
        return httpx.Response(200, headers={"ETag": '"' + hashlib.md5(request.content).hexdigest() + '"'})

    client = httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False, trust_env=False)
    transport = deploy.ZipTransport(admin, client)
    yield candidate, historic, admin, transport, contacted
    client.close()


def apply(setup, **kwargs):
    candidate, historic, admin, transport, _ = setup
    return deploy.apply_deployment(admin, transport, candidate, historic, cloud_write_authorized=True, **kwargs)


def test_forward_preserves_exact_zip_and_private_configuration(setup):
    candidate, _, admin, _, contacted = setup
    before = deepcopy(admin.detail)
    result = apply(setup)
    assert result["status"] == "code_verified" and result["configuration_unchanged"] is True
    assert result["new_resources"] == 0 and result["backup_retained"] is True
    assert result["zip_sha256"] == hashlib.sha256(candidate.read_bytes()).hexdigest()
    assert len(admin.writes) == 1 and admin.detail == before
    assert [r.method for r in contacted] == ["GET", "PUT", "GET"]
    assert "never-print-me" not in json.dumps(result) and "private" not in json.dumps(result)
    assert len(list(deploy.BACKUPS.glob("*.zip"))) == 1


def test_no_authorization_means_no_reads_or_writes(setup):
    candidate, historic, admin, transport, contacted = setup
    with pytest.raises(AdminError, match="CLOUD_WRITE_AUTHORIZATION_REQUIRED"):
        deploy.apply_deployment(admin, transport, candidate, historic)
    assert admin.calls == [] and contacted == []


def test_plan_and_cli_gate_never_create_admin_or_contact_cloud(setup, monkeypatch, capsys):
    candidate, historic, *_ = setup
    monkeypatch.setattr(deploy, "CloudAdmin", lambda: pytest.fail("admin constructed"))
    assert deploy.main(["--package", str(candidate), "--phase04-package", str(historic)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["real_calls"] is False and result["new_resources"] == 0
    assert deploy.main(["--apply"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "CLOUD_WRITE_AUTHORIZATION_REQUIRED"


@pytest.mark.parametrize("field,value", [("env_id", "wrong"), ("region", "ap-beijing"),
    ("package_id", "paid"), ("overrun", True), ("auto_renew", True), ("database_id", "")])
def test_unapproved_trial_target_never_writes(setup, field, value):
    setup[2].bill[field] = value
    with pytest.raises(AdminError):
        apply(setup)
    assert setup[2].writes == [] and setup[4] == []


@pytest.mark.parametrize("field,value", [("Description", "other owner"), ("Namespace", "wrong"),
    ("Type", "Event"), ("Runtime", "Nodejs22.13"), ("MemorySize", 512), ("Timeout", 10),
    ("FunctionName", "another"), ("Status", "Updating")])
def test_wrong_owned_function_never_uploads(setup, field, value):
    setup[2].detail[field] = value
    with pytest.raises(AdminError):
        apply(setup)
    assert setup[2].writes == [] and setup[4] == []


@pytest.mark.parametrize("missing", ["function_exists", "route_exists"])
def test_never_creates_missing_function_or_route(setup, missing):
    setattr(setup[2], missing, False)
    with pytest.raises(AdminError):
        apply(setup)
    assert setup[2].writes == [] and setup[4] == []


def test_wrong_route_is_not_adopted(setup):
    setup[2].route["EnableAuth"] = True
    with pytest.raises(AdminError):
        apply(setup)
    assert setup[2].writes == []


@pytest.mark.parametrize("url", ["https://example.com/a?secret=x", "http://" + deploy.DOWNLOAD_HOST + "/a",
    "https://user@" + deploy.DOWNLOAD_HOST + "/a", "https://" + deploy.DOWNLOAD_HOST + ":444/a",
    "https://" + deploy.DOWNLOAD_HOST + "/a#secret", "https://" + deploy.DOWNLOAD_HOST + "/a\r\n"])
def test_download_url_fail_closed_before_private_http(setup, url):
    setup[2].download_url = url
    with pytest.raises(AdminError, match="UNAPPROVED_DOWNLOAD_TARGET"):
        apply(setup)
    assert setup[4] == [] and setup[2].writes == []


def test_remote_sha_must_match_downloaded_bytes(setup):
    setup[2].remote_hash = "0" * 64
    with pytest.raises(AdminError, match="REMOTE_CODE_CHECKSUM_MISMATCH"):
        apply(setup)
    assert setup[2].writes == []


def test_foreign_current_code_is_never_replaced(setup):
    setup[2].current = package(b"someone-else")
    with pytest.raises(AdminError, match="CURRENT_CODE_NOT_OWNED"):
        apply(setup)
    assert setup[2].writes == []


def test_remote_recompression_and_777_bootstrap_are_accepted_by_members(setup):
    setup[2].current = package(b"phase04", mode=0o777, directories=True)
    assert apply(setup)["status"] == "code_verified"


@pytest.mark.parametrize("extra", ["../unexpected/", "orphan/", "soulcompanion_cloud/../unexpected/"])
def test_directory_entries_must_be_safe_and_belong_to_real_files(setup, extra):
    setup[2].current = package(b"phase04", extra=extra)
    with pytest.raises(AdminError, match="ZIP_CONTENT_UNVERIFIED"):
        apply(setup)
    assert setup[2].writes == []


def test_existing_pc02_is_verified_without_upload_or_code_write(setup):
    setup[2].current = setup[2].forward
    assert apply(setup)["status"] == "already_verified"
    assert setup[2].writes == [] and [r.method for r in setup[4]] == ["GET"]


@pytest.mark.parametrize("mode", [0o644, 0o666])
def test_nonexecutable_remote_bootstrap_is_rejected(setup, mode):
    setup[2].current = package(b"phase04", mode=mode)
    with pytest.raises(AdminError, match="ZIP_CONTENT_UNVERIFIED"):
        apply(setup)
    assert setup[2].writes == []


def test_retained_history_has_pinned_checksum(setup):
    setup[1].write_bytes(package(b"changed-history"))
    with pytest.raises(AdminError, match="PHASE04_PACKAGE_CHECKSUM_MISMATCH"):
        apply(setup)
    assert setup[2].calls == []


@pytest.mark.parametrize("extra", ["../secret", "C:/secret", ".env", "tests/secret.py"])
def test_snapshot_zip_rejects_unsafe_members(setup, extra):
    setup[2].current = package(b"phase04", extra=extra)
    with pytest.raises(AdminError, match="ZIP_CONTENT_UNVERIFIED"):
        apply(setup)
    assert setup[2].writes == []


@pytest.mark.parametrize("field,value", [("date", "../other"), ("date", "2026-99-99"),
    ("sign", "bad\r\nsignature"), ("sign", ""), ("env_region", "ap-beijing"), ("app_id", "../x")])
def test_managed_upload_metadata_is_strict_and_never_sent_to_wrong_target(setup, field, value):
    setattr(setup[2], field, value)
    with pytest.raises(AdminError):
        apply(setup)
    assert setup[2].writes == [] and all(r.method != "PUT" for r in setup[4])


def test_failed_code_request_retains_backup_and_sanitizes_error(setup):
    setup[2].fail_update = True
    with pytest.raises(AdminError, match="CODE_UPDATE_FAILED"):
        apply(setup)
    assert len(list(deploy.BACKUPS.glob("*.zip"))) == 1
    assert len(setup[2].writes) == 1


def test_code_acknowledgement_is_verified(setup):
    setup[2].ack = {"message": "success"}
    with pytest.raises(AdminError, match="CODE_UPDATE_NOT_CONFIRMED"):
        apply(setup)


@pytest.mark.parametrize("field,value", [("MemorySize", 512), ("Handler", "changed.main"),
    ("Environment", {"Variables": [{"Key": "PRIVATE", "Value": "changed-secret"}]})])
def test_postwrite_configuration_change_is_reported_without_leaking_values(setup, field, value):
    setup[2].after_write = lambda admin: admin.detail.update({field: value})
    with pytest.raises(AdminError) as error:
        apply(setup)
    assert "changed-secret" not in str(error.value) and len(setup[2].writes) == 1


def test_zip_upload_failure_never_updates_function(setup):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="private URL/sign"))) as client:
        transport = deploy.ZipTransport(setup[2], client)
        with pytest.raises(AdminError, match="PRIVATE_DOWNLOAD_FAILED"):
            deploy.apply_deployment(setup[2], transport, setup[0], setup[1], cloud_write_authorized=True)
    assert setup[2].writes == []


@pytest.mark.parametrize("status", [302, 403])
def test_upload_redirect_or_failure_never_updates_function(setup, status):
    admin = setup[2]
    contacted = []

    def respond(request):
        contacted.append(request)
        if request.method == "GET":
            return httpx.Response(200, stream=httpx.ByteStream(admin.current))
        return httpx.Response(status, headers={"Location": "https://example.com/private"}, text="private-signature")

    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
        with pytest.raises(AdminError, match="PRIVATE_UPLOAD_NOT_CONFIRMED"):
            deploy.apply_deployment(admin, deploy.ZipTransport(admin, client), setup[0], setup[1], cloud_write_authorized=True)
    assert admin.writes == [] and len(contacted) == 2


def test_original_zip_md5_must_be_confirmed_before_code_update(setup):
    admin = setup[2]

    def respond(request):
        if request.method == "GET":
            return httpx.Response(200, stream=httpx.ByteStream(admin.current))
        return httpx.Response(200, headers={"ETag": '"wrong"'})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(AdminError, match="PRIVATE_UPLOAD_NOT_CONFIRMED"):
            deploy.apply_deployment(admin, deploy.ZipTransport(admin, client), setup[0], setup[1], cloud_write_authorized=True)
    assert admin.writes == []


def test_last_prewrite_remote_change_prevents_update(setup):
    admin = setup[2]
    original = admin.capture
    addresses = 0

    def capture(args, **kwargs):
        nonlocal addresses
        if args[:3] == ["api", "scf", "GetFunctionAddress"]:
            addresses += 1
            if addresses == 3:
                admin.current = package(b"concurrent-change")
        return original(args, **kwargs)

    admin.capture = capture
    with pytest.raises(AdminError, match="CURRENT_CODE_CHANGED"):
        apply(setup)
    assert admin.writes == []


def test_pending_update_is_bounded_then_verified(setup):
    setup[2].pending_reads = 2
    waits = []
    assert apply(setup, sleep=waits.append)["status"] == "code_verified"
    assert waits == [3, 3]


def test_never_retries_a_code_write_when_new_code_does_not_appear(setup):
    old = setup[2].current
    setup[2].after_write = lambda admin: setattr(admin, "current", old)
    waits = []
    with pytest.raises(AdminError, match="UPDATED_CODE_NOT_VERIFIED"):
        apply(setup, sleep=waits.append)
    assert len(setup[2].writes) == 1 and waits == [3, 3, 3, 3]


def test_download_has_strict_byte_limit_and_no_default_client_credentials(setup, monkeypatch):
    admin = setup[2]
    monkeypatch.setattr(deploy, "MAX_PACKAGE_BYTES", 10)
    contacted = []

    def respond(request):
        contacted.append(request)
        assert "Authorization" not in request.headers and "Cookie" not in request.headers
        return httpx.Response(200, stream=httpx.ByteStream(b"too-large-code"))

    with httpx.Client(transport=httpx.MockTransport(respond), headers={"Authorization": "private"},
                      cookies={"private": "value"}, auth=("user", "private")) as client:
        with pytest.raises(AdminError, match="PRIVATE_DOWNLOAD_LIMIT_EXCEEDED"):
            deploy.ZipTransport(admin, client).download()
    assert len(contacted) == 1


def test_api_hash_can_be_base64_but_invalid_hash_never_downloads(setup):
    import base64

    admin = setup[2]
    admin.remote_hash = base64.b64encode(hashlib.sha256(admin.current).digest()).decode()
    assert setup[3].download()[0] == admin.current
    admin.remote_hash = "bad-signed-url-secret"
    with pytest.raises(AdminError, match="REMOTE_CODE_CHECKSUM_UNVERIFIED"):
        setup[3].download()
    assert len(setup[4]) == 1


def test_backup_failure_aborts_before_any_upload_or_function_write(setup, monkeypatch):
    outside = setup[0].parent / "outside"
    monkeypatch.setattr(deploy, "BACKUPS", outside)
    with pytest.raises(AdminError, match="PRIVATE_BACKUP_NOT_RETAINED"):
        apply(setup)
    assert setup[2].writes == [] and all(r.method != "PUT" for r in setup[4])


def test_backup_never_overwrites_foreign_file(setup):
    admin = setup[2]
    deploy.BACKUPS.mkdir(parents=True)
    path = deploy.BACKUPS / (hashlib.sha256(admin.current).hexdigest() + ".zip")
    path.write_bytes(b"foreign-file")
    with pytest.raises(AdminError, match="PRIVATE_BACKUP_NOT_RETAINED"):
        apply(setup)
    assert path.read_bytes() == b"foreign-file" and admin.writes == []


def test_rollback_uses_only_pinned_history_and_keeps_config(setup):
    candidate, historic, admin, _, _ = setup
    admin.current = candidate.read_bytes()
    admin.forward = historic.read_bytes()
    assert apply(setup, rollback=True)["status"] == "code_verified"
    assert admin.current == historic.read_bytes() and len(admin.writes) == 1
