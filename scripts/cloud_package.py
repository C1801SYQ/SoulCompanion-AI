"""Build a reproducible, Linux CPython 3.11 HTTP-function package.

Only the independent cloud API is eligible for packaging. Credentials, local
databases, media, and the inference runtime are never package inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ZIP_DATE = (2020, 1, 1, 0, 0, 0)
MAX_PACKAGE_BYTES = 50 * 1024 * 1024
MAX_EXPANDED_BYTES = 250 * 1024 * 1024
# Pin the complete lightweight dependency graph, including transitive packages.
# These versions match the validated web constraints plus httpx's dependencies.
DEPENDENCIES = {
    "annotated-doc": "0.0.5",
    "annotated-types": "0.8.0",
    "anyio": "4.15.1",
    "certifi": "2026.7.22",
    "click": "8.5.0",
    "fastapi": "0.142.2",
    "h11": "0.16.0",
    "httpcore": "1.0.9",
    "httpx": "0.28.1",
    "idna": "3.20",
    "opentelemetry-api": "1.45.0",
    "pydantic": "2.13.5",
    "pydantic-core": "2.46.5",
    "starlette": "1.7.0",
    "typing-extensions": "4.16.0",
    "typing-inspection": "0.4.4",
    "uvicorn": "0.54.0",
}


class PackageError(RuntimeError):
    """A safe error: never include captured process output or credentials."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def bootstrap_bytes(source: bytes) -> bytes:
    text = source.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("#!/bin/sh\n") or "--port 9000" not in text:
        raise PackageError("Invalid HTTP bootstrap")
    if "PYTHONPATH" not in text:
        text = text.replace("exec python3", 'export PYTHONPATH="/var/user/third_party${PYTHONPATH:+:$PYTHONPATH}"\nexec python3', 1)
    return (text.rstrip("\n") + "\n").encode("utf-8")


def collect_source(source: Path) -> dict[str, bytes]:
    """Positive source allowlist; unrelated files are ignored even if tracked."""
    source = source.resolve()
    requirements = source / "requirements-cloud.txt"
    if requirements.is_file():
        if requirements.is_symlink():
            raise PackageError("Unsafe requirements file")
        for line in requirements.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
            if not match or DEPENDENCIES.get(normalize_name(match[1])) != match[2]:
                raise PackageError("Cloud API requirements diverge from the Linux lock")
    files = [source / "app.py", source / "scf_bootstrap"]
    module = source / "soulcompanion_cloud"
    if module.is_symlink() or not module.is_dir():
        raise PackageError("Cloud API module missing or unsafe")
    files.extend(sorted(module.rglob("*.py")))
    result = {}
    for path in files:
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source):
            raise PackageError("Unsafe source file")
        if any(part in {"tests", "__pycache__", ".git", ".env"} for part in path.relative_to(source).parts):
            continue
        name = path.relative_to(source).as_posix()
        data = path.read_bytes()
        if name == "scf_bootstrap":
            data = bootstrap_bytes(data)
        else:
            data = data.replace(b"\r\n", b"\n")
        result[name] = data
    return result


def download_wheels(destination: Path) -> None:
    """Download Linux wheels on any host, without executing dependency code."""
    requirement = destination / "requirements-locked.txt"
    requirement.write_text("".join(f"{name}=={version}\n" for name, version in sorted(DEPENDENCIES.items())), encoding="utf-8")
    command = [
        sys.executable, "-m", "pip", "download", "--disable-pip-version-check",
        "--only-binary=:all:", "--no-deps", "--platform", "manylinux2014_x86_64",
        "--implementation", "cp", "--python-version", "3.11", "--abi", "cp311",
        "--dest", str(destination), "--requirement", str(requirement),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL, timeout=240, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PackageError("Linux wheel download failed") from error
    if completed.returncode:
        raise PackageError("Linux wheel download failed; raw pip output withheld")


def wheel_files(wheels: Path) -> tuple[dict[str, bytes], list[dict[str, str]]]:
    """Read sanitized wheel entries; never extract arbitrary archive paths."""
    files: dict[str, bytes] = {}
    packages = []
    seen = set()
    total_bytes = 0
    for wheel in sorted(wheels.glob("*.whl")):
        if wheel.is_symlink():
            raise PackageError("Unsafe wheel")
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise PackageError("Wheel metadata missing")
            metadata = archive.read(metadata_names[0]).decode("utf-8")
            name_match = re.search(r"^Name: (.+)$", metadata, re.MULTILINE)
            version_match = re.search(r"^Version: (.+)$", metadata, re.MULTILINE)
            if not name_match or not version_match:
                raise PackageError("Invalid wheel metadata")
            name, version = normalize_name(name_match[1].strip()), version_match[1].strip()
            if name in seen or DEPENDENCIES.get(name) != version:
                raise PackageError("Unexpected or duplicate dependency")
            # Reject native wheels for a different interpreter or OS.
            tag = wheel.name.rsplit("-", 3)[-3:]
            if len(tag) != 3 or not (tag[2] == "any.whl" or (tag[0] == "cp311" and "manylinux" in tag[2] and "x86_64" in tag[2])):
                raise PackageError("Wheel platform is not Linux CPython 3.11")
            seen.add(name)
            packages.append({"name": name, "version": version, "wheel_sha256": sha256(wheel.read_bytes())})
            for info in archive.infolist():
                path = PurePosixPath(info.filename)
                if "\\" in info.orig_filename or path.is_absolute() or ".." in path.parts or any(":" in part for part in path.parts):
                    raise PackageError("Unsafe wheel path")
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise PackageError("Wheel symlinks are forbidden")
                if info.is_dir():
                    continue
                parts = path.parts
                if any(part in {"tests", "__pycache__"} for part in parts) or path.suffix in {".pyc", ".pyo", ".pyd", ".exe"}:
                    continue
                if parts[0].endswith(".data"):
                    if len(parts) < 3 or parts[1] not in {"purelib", "platlib"}:
                        continue
                    path = PurePosixPath(*parts[2:])
                name_in_zip = "third_party/" + path.as_posix()
                total_bytes += info.file_size
                if total_bytes > MAX_EXPANDED_BYTES or name_in_zip in files:
                    raise PackageError("Dependency archive exceeds limits or overlaps")
                files[name_in_zip] = archive.read(info)
    if seen != set(DEPENDENCIES):
        raise PackageError("Incomplete dependency set")
    return files, packages


def write_archive(output: Path, files: dict[str, bytes]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".partial")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | (0o755 if name == "scf_bootstrap" else 0o644)) << 16
                archive.writestr(info, data)
        if temporary.stat().st_size > MAX_PACKAGE_BYTES:
            raise PackageError("Function ZIP exceeds the configured package safety limit")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def build_package(source: Path, output: Path, *, skip_dependencies: bool = False, wheels: Path | None = None) -> dict:
    files = collect_source(source)
    packages = []
    if not skip_dependencies:
        if wheels is None:
            with tempfile.TemporaryDirectory(prefix="sc-cloud-wheels-") as temporary:
                wheel_path = Path(temporary)
                download_wheels(wheel_path)
                dependencies, packages = wheel_files(wheel_path)
        else:
            dependencies, packages = wheel_files(wheels)
        files.update(dependencies)
    write_archive(output, files)
    manifest = {
        "format_version": 1,
        "runtime": "Python3.11", "platform": "manylinux2014_x86_64",
        "entrypoint": "scf_bootstrap", "port": 9000,
        "dependencies_included": not skip_dependencies,
        "deployable": not skip_dependencies,
        "zip_sha256": sha256(output.read_bytes()),
        "compressed_bytes": output.stat().st_size,
        "expanded_bytes": sum(map(len, files.values())),
        "file_count": len(files),
        "source_files": [{"path": name, "sha256": sha256(data)} for name, data in sorted(files.items()) if not name.startswith("third_party/")],
        "packages": packages,
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".test-artifacts/cloudbase-phase04/sc-v2-api.zip")
    parser.add_argument("--skip-dependencies", action="store_true", help="Source-only verification; this package cannot be deployed")
    parser.add_argument("--wheels", type=Path, help="Use an already downloaded exact wheel set")
    arguments = parser.parse_args(argv)
    try:
        manifest = build_package(ROOT / "cloud/api", arguments.output, skip_dependencies=arguments.skip_dependencies, wheels=arguments.wheels)
    except (PackageError, OSError, ValueError, zipfile.BadZipFile) as error:
        print(json.dumps({"success": False, "error": str(error) if isinstance(error, PackageError) else "Package build failed"}))
        return 1
    print(json.dumps({"success": True, "deployable": manifest["deployable"], "zip_sha256": manifest["zip_sha256"], "file_count": manifest["file_count"], "compressed_bytes": manifest["compressed_bytes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
