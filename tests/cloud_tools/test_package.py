"""Boundary tests for cloud packaging and the controlled deployment tool."""

import json
from pathlib import Path
import stat
import zipfile

import pytest

from scripts import cloud_package
from scripts import cloud_deploy
from scripts.cloud_admin import AdminError, ENV_ID


def api_source(tmp_path):
    source = tmp_path / "api"
    module = source / "soulcompanion_cloud"
    module.mkdir(parents=True)
    (source / "app.py").write_text("from soulcompanion_cloud.app import app\n")
    (source / "scf_bootstrap").write_bytes(b"#!/bin/sh\r\nset -eu\r\nexec python3 -m uvicorn app:app --port 9000\r\n")
    (module / "__init__.py").write_text("")
    (module / "app.py").write_text("app = None\n")
    return source


def test_package_is_deterministic_and_bootstrap_is_executable(tmp_path):
    source = api_source(tmp_path)
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    first_manifest = cloud_package.build_package(source, first, skip_dependencies=True)
    second_manifest = cloud_package.build_package(source, second, skip_dependencies=True)
    assert first.read_bytes() == second.read_bytes()
    assert first_manifest == second_manifest
    assert first_manifest["deployable"] is False
    with zipfile.ZipFile(first) as archive:
        info = archive.getinfo("scf_bootstrap")
        assert stat.S_IMODE(info.external_attr >> 16) == 0o755
        assert info.date_time == cloud_package.ZIP_DATE
        bootstrap = archive.read("scf_bootstrap")
        assert b"\r" not in bootstrap
        assert b"/var/user/third_party" in bootstrap


def test_package_allowlist_excludes_credentials_media_and_inference(tmp_path):
    source = api_source(tmp_path)
    for name in (".env", "credentials.json", "recording.wav", "capture.jpg", "database.sqlite", "requirements.txt"):
        (source / name).write_text("must not ship")
    for directory in ("tests", "__pycache__", "torch", "node_modules"):
        (source / directory).mkdir()
        (source / directory / "secret.py").write_text("must not ship")
    output = tmp_path / "api.zip"
    cloud_package.build_package(source, output, skip_dependencies=True)
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"app.py", "scf_bootstrap", "soulcompanion_cloud/__init__.py", "soulcompanion_cloud/app.py"}
    manifest = json.loads(output.with_suffix(".manifest.json").read_text())
    assert "must not ship" not in json.dumps(manifest)


def test_runtime_requirements_cannot_silently_diverge_from_locked_package(tmp_path):
    source = api_source(tmp_path)
    (source / "requirements-cloud.txt").write_text("torch==2.0.0\n")
    with pytest.raises(cloud_package.PackageError, match="requirements diverge"):
        cloud_package.collect_source(source)


def test_source_symlink_cannot_escape_allowlist(tmp_path):
    source = api_source(tmp_path)
    outside = tmp_path / "private.py"
    outside.write_text("private")
    target = source / "soulcompanion_cloud" / "outside.py"
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this host")
    with pytest.raises(cloud_package.PackageError, match="Unsafe source"):
        cloud_package.collect_source(source)


def fake_wheel(tmp_path, *, entry="demo/__init__.py", platform="py3-none-any", version="1.0"):
    wheel = tmp_path / f"demo-{version}-{platform}.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"demo-{version}.dist-info/METADATA", f"Name: demo\nVersion: {version}\n")
        # Preserve hostile spelling even on Windows (ZipInfo's constructor
        # otherwise normalizes the host's path separator).
        info = zipfile.ZipInfo("placeholder")
        info.filename = entry
        archive.writestr(info, "")
    return wheel


@pytest.mark.parametrize("entry", ["../escape.py", "/escape.py", "C:/private.py", "demo\\escape.py"])
def test_wheel_paths_cannot_escape(tmp_path, monkeypatch, entry):
    monkeypatch.setattr(cloud_package, "DEPENDENCIES", {"demo": "1.0"})
    fake_wheel(tmp_path, entry=entry)
    with pytest.raises(cloud_package.PackageError, match="Unsafe wheel path"):
        cloud_package.wheel_files(tmp_path)


def test_windows_native_wheel_and_unpinned_dependencies_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_package, "DEPENDENCIES", {"demo": "1.0"})
    wheel = fake_wheel(tmp_path, platform="cp311-cp311-win_amd64")
    with pytest.raises(cloud_package.PackageError, match="Wheel platform"):
        cloud_package.wheel_files(tmp_path)
    wheel.unlink()
    fake_wheel(tmp_path, version="2.0")
    with pytest.raises(cloud_package.PackageError, match="Unexpected"):
        cloud_package.wheel_files(tmp_path)


def test_pip_failure_output_is_not_exposed(tmp_path, monkeypatch, capsys):
    class Failed:
        returncode = 1
        stdout = b"super-secret-token"
        stderr = b"super-secret-password"

    monkeypatch.setattr(cloud_package.subprocess, "run", lambda *args, **kwargs: Failed())
    with pytest.raises(cloud_package.PackageError) as failure:
        cloud_package.download_wheels(tmp_path)
    assert "super-secret" not in str(failure.value)
    assert capsys.readouterr().out == ""


class FakeAdmin:
    domain = ENV_ID + "-1501181209.ap-shanghai.app.tcloudbase.com"

    def __init__(self, *, functions=None, detail=None, routes=None):
        self.functions = functions or []
        self.detail = detail or {}
        self.routes = routes or []

    def preflight(self):
        return {"env_id": ENV_ID, "package_id": "baas_trial", "overrun": False, "auto_renew": False}

    def capture(self, args, **kwargs):
        if args[:2] == ["fn", "list"]:
            return json.dumps({"data": {"Functions": self.functions}})
        if args[:2] == ["fn", "detail"]:
            return json.dumps({"data": self.detail})
        raise AssertionError("A planning run must not write")

    def api(self, action, body):
        assert action == "DescribeHTTPServiceRoute"
        assert body["EnvId"] == ENV_ID
        return {"Domains": [{"Domain": self.domain, "Routes": self.routes}]}


def owned_function():
    return {"FunctionName": cloud_deploy.FUNCTION, "Description": cloud_deploy.OWNER_MARKER, "Namespace": ENV_ID, "Type": "HTTP", "Runtime": "Python3.11", "MemorySize": 256, "Timeout": 3, "Environment": {"Variables": [{"Key": "CLOUDBASE_APIKEY", "Value": "withheld-fixture"}]}}


def owned_route():
    return {"Path": "/", "UpstreamResourceType": "WEB_SCF", "UpstreamResourceName": cloud_deploy.FUNCTION, "Enable": True, "EnableAuth": False, "EnableSafeDomain": False, "EnablePathTransmission": True, "QPSPolicy": {"QPSTotal": 100, "QPSPerClient": {"LimitBy": "ClientIP", "LimitValue": 5}}}


def test_dry_plan_is_bounded_and_does_not_return_function_secrets():
    admin = FakeAdmin(functions=[{"FunctionName": cloud_deploy.FUNCTION}], detail=owned_function(), routes=[owned_route()])
    plan, exists, route_exists = cloud_deploy.inspect_resources(admin)
    assert exists is True and route_exists is True
    assert plan["memory_mb"] == 256 and plan["timeout_seconds"] == 3 and plan["prewarm"] is False
    assert "withheld-fixture" not in json.dumps(plan)
    assert plan["function_action"] == "update_owned"


def test_colliding_function_and_gateway_block_without_writes():
    detail = owned_function()
    detail["Description"] = "Another project"
    with pytest.raises(AdminError, match="FUNCTION_COLLISION"):
        cloud_deploy.inspect_resources(FakeAdmin(functions=[{"FunctionName": cloud_deploy.FUNCTION}], detail=detail))
    route = owned_route()
    route["UpstreamResourceName"] = "another-function"
    with pytest.raises(AdminError, match="GATEWAY_ROUTE_COLLISION"):
        cloud_deploy.inspect_resources(FakeAdmin(routes=[route]))


def test_paid_preflight_block_propagates_before_any_resource_calls():
    class Paid(FakeAdmin):
        def preflight(self):
            raise AdminError("PAID_RESOURCE_REQUIRED_OR_BILLING_UNVERIFIED")

        def capture(self, *args, **kwargs):
            raise AssertionError("No later operations are allowed")

    with pytest.raises(AdminError, match="PAID_RESOURCE_REQUIRED"):
        cloud_deploy.inspect_resources(Paid())


def test_private_config_secret_file_is_outside_package_and_always_removed(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    with pytest.raises(RuntimeError):
        with cloud_deploy.private_config(tmp_path, code, {"CLOUDBASE_APIKEY": "withheld-fixture"}) as path:
            assert path.parent == tmp_path and not path.is_relative_to(code)
            config = json.loads(path.read_text())
            assert config["functions"][0]["envVariables"]["CLOUDBASE_APIKEY"] == "withheld-fixture"
            assert config["functions"][0]["installDependency"] is False
            raise RuntimeError("failure")
    assert not path.exists()
    assert list(code.iterdir()) == []


def test_exact_cors_and_environment_guards():
    with pytest.raises(AdminError, match="WRONG_ENVIRONMENT"):
        cloud_deploy.validate_variables({"CLOUDBASE_APIKEY": "withheld-fixture", "CLOUDBASE_ENV_ID": "other-env"})
    with pytest.raises(AdminError, match="EXACT_CORS"):
        cloud_deploy.validate_variables({"CLOUDBASE_APIKEY": "withheld-fixture", "CLOUD_ALLOWED_ORIGINS": "https://*.example.com"})
    result = cloud_deploy.validate_variables({"CLOUDBASE_APIKEY": "withheld-fixture", "CLOUD_ALLOWED_ORIGINS": "http://127.0.0.1:5176", "UNRELATED_SECRET": "omit"})
    assert set(result) == {"CLOUDBASE_APIKEY", "CLOUDBASE_ENV_ID", "CLOUD_ALLOWED_ORIGINS"}


def test_source_only_package_is_never_deployable(tmp_path):
    source = api_source(tmp_path)
    output = tmp_path / "api.zip"
    cloud_package.build_package(source, output, skip_dependencies=True)
    with pytest.raises(AdminError, match="PACKAGE_NOT_DEPLOYABLE"):
        cloud_deploy.validate_package(output)


def test_deploy_does_not_pass_key_to_cli_and_cleans_up_failure(tmp_path, monkeypatch, capsys):
    plan, existing, route_exists = cloud_deploy.inspect_resources(FakeAdmin())
    monkeypatch.setattr(cloud_deploy, "validate_package", lambda path: {"zip_sha256": "abc", "package_bytes": 10})
    monkeypatch.setattr(cloud_deploy, "inspect_resources", lambda admin: (plan, existing, route_exists))
    monkeypatch.setattr(cloud_deploy, "extract_package", lambda package, code: (code / "app.py").write_text("app=None"))
    monkeypatch.setattr(cloud_deploy, "load_private_environment", lambda: {"CLOUDBASE_APIKEY": "withheld-fixture"})
    monkeypatch.setattr(cloud_deploy, "ARTIFACTS", tmp_path)

    class FailDeploy:
        def capture(self, args, **kwargs):
            assert "withheld-fixture" not in " ".join(args)
            assert "--yes" not in args and "--force" not in args
            assert args[args.index("--deployMode") + 1] == "cos"
            config = Path(args[args.index("--config-file") + 1])
            assert "withheld-fixture" in config.read_text()
            raise AdminError("CLI_OPERATION_FAILED")

    with pytest.raises(AdminError, match="CLI_OPERATION_FAILED"):
        cloud_deploy.apply_deployment(FailDeploy(), tmp_path / "api.zip", plan, existing, route_exists)
    assert list(tmp_path.iterdir()) == []
    assert capsys.readouterr().out == ""


def test_default_gateway_uses_existing_domain_route_api(tmp_path, monkeypatch):
    plan, existing, route_exists = cloud_deploy.inspect_resources(FakeAdmin())
    verified = {**plan, "function_action": "update_owned", "route_action": "retain_owned"}
    states = iter([(plan, existing, route_exists), (verified, True, True)])
    monkeypatch.setattr(cloud_deploy, "inspect_resources", lambda admin: next(states))
    monkeypatch.setattr(cloud_deploy, "validate_package", lambda path: {"zip_sha256": "abc", "package_bytes": 10})
    monkeypatch.setattr(cloud_deploy, "extract_package", lambda package, code: None)
    monkeypatch.setattr(cloud_deploy, "load_private_environment", lambda: {"CLOUDBASE_APIKEY": "withheld-fixture"})
    monkeypatch.setattr(cloud_deploy, "ARTIFACTS", tmp_path)
    writes = []

    class SuccessfulDeploy:
        def capture(self, args, **kwargs):
            assert args[:2] == ["fn", "deploy"]
            assert "withheld-fixture" not in " ".join(args)
            return json.dumps({"success": True, "results": [{"name": cloud_deploy.FUNCTION, "status": "success"}]})

        def api(self, action, body, *, write=False):
            writes.append((action, body, write))
            return {}

    result = cloud_deploy.apply_deployment(SuccessfulDeploy(), tmp_path / "api.zip", plan, existing, route_exists)
    assert writes == [("CreateHTTPServiceRoute", {
        "EnvId": ENV_ID,
        "Domain": {"Domain": FakeAdmin.domain, "Routes": [owned_route()]},
    }, True)]
    assert result["route_action"] == "retain_owned"
    assert result["gateway_qps_total"] == 100 and result["gateway_qps_per_ip"] == 5
    assert "withheld-fixture" not in (tmp_path / "deployment-public.json").read_text()


@pytest.mark.parametrize("function_exists", [False, True])
def test_missing_post_deploy_resources_cannot_publish_success(tmp_path, monkeypatch, function_exists):
    plan, existing, route_exists = cloud_deploy.inspect_resources(FakeAdmin())
    states = iter([(plan, existing, route_exists), (plan, function_exists, False)])
    monkeypatch.setattr(cloud_deploy, "inspect_resources", lambda admin: next(states))
    monkeypatch.setattr(cloud_deploy, "validate_package", lambda path: {})
    monkeypatch.setattr(cloud_deploy, "extract_package", lambda package, code: None)
    monkeypatch.setattr(cloud_deploy, "load_private_environment", lambda: {"CLOUDBASE_APIKEY": "withheld-fixture"})
    monkeypatch.setattr(cloud_deploy, "ARTIFACTS", tmp_path)

    class EmptyAfterDeploy:
        def capture(self, args, **kwargs):
            return json.dumps({"success": True, "results": [{"name": cloud_deploy.FUNCTION, "status": "success"}]})

        def api(self, *args, **kwargs):
            return {}

    with pytest.raises(AdminError, match="DEPLOYED_RESOURCES_NOT_PRESENT"):
        cloud_deploy.apply_deployment(EmptyAfterDeploy(), tmp_path / "api.zip", plan, existing, route_exists)
    assert not (tmp_path / "deployment-public.json").exists()
    assert list(tmp_path.iterdir()) == []
