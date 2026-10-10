"""PC02 family contracts use synthetic authenticated accounts and local adapters."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
from copy import deepcopy
from uuid import UUID

from fastapi.testclient import TestClient
import httpx
import pytest

from cloud.api.soulcompanion_cloud.app import create_app
from cloud.api.soulcompanion_cloud.auth import AppPrincipal
from cloud.api.soulcompanion_cloud.config import Settings
from cloud.api.soulcompanion_cloud.errors import CloudError
from cloud.api.soulcompanion_cloud.repository import (
    COLLECTIONS,
    CloudBaseDocumentRepository,
    InMemoryRepository,
)
from cloud.api.soulcompanion_cloud.models import ChildWrite
from cloud.api.soulcompanion_cloud.service import ApplicationService


AGE_BANDS = ("0-2", "3-5", "6-8", "9-12", "13-15", "16-18")
ROOT = Path(__file__).resolve().parents[2]


class FamilyVerifier:
    async def verify(self, token):
        if token not in {"family-account-a", "family-account-b"}:
            raise CloudError(401, "unauthorized", "Please sign in again.")
        return AppPrincipal(token, "synthetic-family-environment")

    async def ready(self):
        return True


def auth(account="a"):
    return {"Authorization": f"Bearer family-account-{account}"}


@pytest.fixture
def family_repository():
    return InMemoryRepository(family_identity_enabled=True)


@pytest.fixture
def family_client(family_repository):
    with TestClient(create_app(Settings(private_rate_limit=1000), family_repository, FamilyVerifier())) as client:
        yield client


@pytest.mark.parametrize("age_band", (*AGE_BANDS, None))
def test_optional_age_band_create_update_and_explicit_clear(family_client, age_band):
    created = family_client.post(
        "/api/v2/children",
        headers=auth(),
        json={"nickname": "合成儿童档案", "age_band": age_band},
    )
    assert created.status_code == 201
    assert created.json()["age_band"] == age_band
    path = f"/api/v2/children/{created.json()['id']}"
    assert family_client.patch(path, headers=auth(), json={"nickname": "新私有昵称"}).json()["age_band"] == age_band
    assert (
        family_client.patch(path, headers=auth(), json={"nickname": "新私有昵称", "age_band": "9-12"}).json()[
            "age_band"
        ]
        == "9-12"
    )
    assert (
        family_client.patch(path, headers=auth(), json={"nickname": "新私有昵称", "age_band": None}).json()["age_band"]
        is None
    )


def test_old_child_records_without_age_are_readable_without_migration(family_client, family_repository):
    created = family_client.post("/api/v2/children", headers=auth(), json={"nickname": "旧昵称"}).json()
    family_repository.records["children"][created["id"]].pop("age_band", None)
    assert family_client.get(f"/api/v2/children/{created['id']}", headers=auth()).json()["age_band"] is None
    assert family_client.get("/api/v2/children", headers=auth()).json()["items"][0]["age_band"] is None


@pytest.mark.parametrize("age_band", ["all", "全部", "6～8", "18-20", "", 6, ["0-2"]])
def test_invalid_age_band_rejected(family_client, age_band):
    assert (
        family_client.post(
            "/api/v2/children", headers=auth(), json={"nickname": "合成昵称", "age_band": age_band}
        ).status_code
        == 422
    )


def test_age_band_update_keeps_existing_ownership_boundary(family_client):
    created = family_client.post(
        "/api/v2/children", headers=auth(), json={"nickname": "私有昵称", "age_band": "6-8"}
    ).json()
    path = f"/api/v2/children/{created['id']}"
    assert family_client.get(path, headers=auth("b")).status_code == 404
    assert family_client.patch(path, headers=auth("b"), json={"nickname": "越权", "age_band": "3-5"}).status_code == 404
    assert family_client.get(path, headers=auth()).json()["age_band"] == "6-8"


def test_family_features_disabled_honestly_keep_phase04_child_contract():
    repository = InMemoryRepository()
    with TestClient(create_app(Settings(), repository, FamilyVerifier())) as client:
        assert client.get("/api/v2/capabilities", headers=auth()).json() == {
            "child_age_band": False,
            "parent_profile": False,
        }
        for method, body in [("GET", None), ("PUT", {"nickname": "合成家长"})]:
            response = client.request(method, "/api/v2/parent-profile", headers=auth(), json=body)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "feature_unavailable"
        assert not repository.parent_profiles
        child = client.post("/api/v2/children", headers=auth(), json={"nickname": "兼容昵称"})
        assert child.status_code == 201
        path = f"/api/v2/children/{child.json()['id']}"
        for body in [{"nickname": "新昵称", "age_band": None}, {"nickname": "新昵称", "age_band": "0-2"}]:
            assert client.post("/api/v2/children", headers=auth(), json=body).status_code == 503
            assert client.patch(path, headers=auth(), json=body).status_code == 503
        assert client.patch(path, headers=auth(), json={"nickname": "兼容新昵称"}).status_code == 200
        assert client.get("/api/v2/readyz").status_code == 200


def test_parent_profile_is_separate_stable_and_owner_private(family_client, family_repository):
    user = family_client.get("/api/v2/me", headers=auth()).json()
    family_client.patch("/api/v2/me", headers=auth(), json={"display_name": "私有姓名"})
    child = family_client.post(
        "/api/v2/children", headers=auth(), json={"nickname": "孩子私有名字", "age_band": "3-5"}
    ).json()
    assert family_client.get("/api/v2/parent-profile", headers=auth()).json() is None
    created = family_client.put("/api/v2/parent-profile", headers=auth(), json={"nickname": "  合成家长  "})
    assert created.status_code == 200
    profile = created.json()
    assert set(profile) == {"id", "nickname", "created_at", "updated_at"}
    UUID(profile["id"])
    assert profile["id"] not in {user["id"], child["id"]}
    assert profile["nickname"] == "合成家长"
    assert (
        "family-account" not in created.text and "私有姓名" not in created.text and "孩子私有名字" not in created.text
    )
    changed = family_client.put("/api/v2/parent-profile", headers=auth(), json={"nickname": "家长新昵称"}).json()
    assert changed["id"] == profile["id"] and changed["created_at"] == profile["created_at"]
    assert family_client.get("/api/v2/parent-profile", headers=auth()).json() == changed
    assert family_client.get("/api/v2/parent-profile", headers=auth("b")).json() is None
    assert family_client.get("/api/v2/me", headers=auth()).json()["display_name"] == "私有姓名"
    assert len(family_repository.parent_profiles) == 1


def test_duplicate_nicknames_allowed_but_public_ids_distinct(family_client):
    profiles = [
        family_client.put("/api/v2/parent-profile", headers=auth(account), json={"nickname": "同名家长"}).json()
        for account in ("a", "b")
    ]
    assert profiles[0]["nickname"] == profiles[1]["nickname"]
    assert profiles[0]["id"] != profiles[1]["id"]


def test_first_parent_profile_save_converges_atomically(family_client, family_repository):
    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(
            executor.map(
                lambda _: family_client.put("/api/v2/parent-profile", headers=auth(), json={"nickname": "合成家长"}),
                range(20),
            )
        )
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    assert len({response.json()["created_at"] for response in responses}) == 1
    assert len(family_repository.parent_profiles) == 1


@pytest.mark.parametrize(
    "nickname",
    [
        "",
        " ",
        "a",
        "a" * 25,
        12,
        None,
        "家长<script>",
        "https://example.test",
        "家长\n昵称",
        "家长\t昵称",
        "家长\u202e昵称",
        "家长\u200b昵称",
        "昵称😀",
        "家长@昵称",
    ],
)
def test_public_nickname_rejects_unsafe_and_invalid_input(family_client, nickname):
    assert family_client.put("/api/v2/parent-profile", headers=auth(), json={"nickname": nickname}).status_code == 422


@pytest.mark.parametrize(
    "nickname,normalized",
    [("e\u0301家长", "é家长"), ("家长 ·_1-A", "家长 ·_1-A"), ("甲乙", "甲乙"), ("a" * 24, "a" * 24)],
)
def test_public_nickname_nfc_and_allowed_characters(family_client, nickname, normalized):
    response = family_client.put("/api/v2/parent-profile", headers=auth(), json={"nickname": nickname})
    assert response.status_code == 200 and response.json()["nickname"] == normalized


@pytest.mark.parametrize(
    "extra",
    [
        {"uid": "spoof"},
        {"openid": "spoof"},
        {"owner_user_id": "spoof"},
        {"child_profile_id": "spoof"},
        {"avatar": "https://example.test"},
    ],
)
def test_public_profile_rejects_client_identity_and_unimplemented_fields(family_client, extra):
    response = family_client.put("/api/v2/parent-profile", headers=auth(), json={"nickname": "合成家长", **extra})
    assert response.status_code == 422 and "spoof" not in response.text


@pytest.mark.parametrize("path", ["capabilities", "parent-profile"])
@pytest.mark.parametrize("headers", [{}, {"x-wx-openid": "spoof"}, {"Authorization": "Bearer expired"}])
def test_family_routes_require_verified_user(family_client, path, headers):
    assert family_client.get(f"/api/v2/{path}", headers=headers).status_code == 401


def canonical_checksum(manifest):
    return sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_incremental_manifest_binds_untouched_phase04_schema():
    from cloud.api.soulcompanion_cloud.family_identity import FAMILY_SCHEMA_CHECKSUM, PHASE04_SCHEMA_CHECKSUM

    base = json.loads((ROOT / "cloud/schema/001_metadata.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "cloud/schema/002_family_identity.json").read_text(encoding="utf-8"))
    assert canonical_checksum(base) == PHASE04_SCHEMA_CHECKSUM
    assert manifest["base_schema"] == {
        "marker_id": "phase04",
        "owner": "SoulCompanion-AI/phase04",
        "version": 1,
        "checksum": PHASE04_SCHEMA_CHECKSUM,
    }
    assert manifest["version"] == 2 and manifest["marker_id"] == "pc02-family-identity"
    assert manifest["owner"] == "SoulCompanion-AI/pc02" and manifest["acl"] == "ADMINONLY"
    assert canonical_checksum(manifest) == FAMILY_SCHEMA_CHECKSUM
    assert [item["name"] for item in manifest["collections"]] == ["sc_v2_parent_profiles"]
    assert manifest["collections"][0]["indexes"] == [
        {"name": "pc02_parent_owner_unique", "unique": True, "keys": [["owner_user_id", "1"]]}
    ]


class FamilyDocumentServer:
    """Deterministic official wire fake, never a live CloudBase request."""

    def __init__(self):
        self.records = {name: {} for name in COLLECTIONS.values()}
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        assert request.url.host == "synthetic-family-env.api.tcloudbasegateway.com"
        assert request.headers["authorization"] == "Bearer synthetic-server-key"
        suffix = request.url.path.split("/collections/", 1)[1].split("/")
        records = self.records[suffix[0]]
        if len(suffix) == 3:
            assert request.method == "GET"
            return (
                httpx.Response(200, json=records[suffix[2]]) if suffix[2] in records else httpx.Response(404, json={})
            )
        body = json.loads(request.content) if request.content else {}
        if request.method == "POST":
            record = body["data"][0]
            if record["_id"] in records:
                return httpx.Response(500, json={"code": "DATABASE_REQUEST_FAILED"})
            records[record["_id"]] = deepcopy(record)
            return httpx.Response(201, json={"insertedIds": [record["_id"]]})
        query = body["query"] if request.method == "PATCH" else json.loads(request.url.params.get("query", "{}"))
        matches = [
            record for record in records.values() if all(record.get(key) == value for key, value in query.items())
        ]
        if request.method == "PATCH":
            assert body["upsert"] is False and body["multi"] is False and body["replaceMode"] is False
            for record in matches[:1]:
                record.update(body["data"]["$set"])
            return httpx.Response(200, json={"matched": len(matches[:1]), "updated": len(matches[:1])})
        if request.url.params.get("count") == "true":
            return httpx.Response(200, json={"total": len(matches)})
        return httpx.Response(200, json={"list": deepcopy(matches[:1])})


def seed_markers(server):
    from cloud.api.soulcompanion_cloud.family_identity import FAMILY_SCHEMA_CHECKSUM, PHASE04_SCHEMA_CHECKSUM

    server.records[COLLECTIONS["schema"]]["phase04"] = {
        "_id": "phase04",
        "owner": "SoulCompanion-AI/phase04",
        "version": 1,
        "checksum": PHASE04_SCHEMA_CHECKSUM,
    }
    server.records[COLLECTIONS["schema"]]["pc02-family-identity"] = {
        "_id": "pc02-family-identity",
        "owner": "SoulCompanion-AI/pc02",
        "version": 2,
        "checksum": FAMILY_SCHEMA_CHECKSUM,
    }


WIRE_SETTINGS = Settings(env_id="synthetic-family-env", api_key="synthetic-server-key")


@pytest.mark.parametrize(
    "marker,field,value",
    [
        ("pc02-family-identity", "owner", "foreign-owner"),
        ("pc02-family-identity", "_id", "different-marker"),
        ("pc02-family-identity", "version", 0),
        ("pc02-family-identity", "version", True),
        ("pc02-family-identity", "checksum", "foreign-checksum"),
        ("phase04", "owner", "foreign-owner"),
        ("phase04", "_id", "different-marker"),
        ("phase04", "version", 2),
        ("phase04", "checksum", "foreign-checksum"),
    ],
)
def test_runtime_readiness_requires_exact_incremental_and_base_markers(marker, field, value):
    async def scenario():
        server = FamilyDocumentServer()
        seed_markers(server)
        server.records[COLLECTIONS["schema"]][marker][field] = value
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
            assert await CloudBaseDocumentRepository(WIRE_SETTINGS, client).family_identity_ready() is False
        assert all(request.method == "GET" for request in server.requests)

    asyncio.run(scenario())


def test_runtime_readiness_is_separate_from_phase04_and_only_reads():
    async def scenario():
        server = FamilyDocumentServer()
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
            repository = CloudBaseDocumentRepository(WIRE_SETTINGS, client)
            assert await repository.family_identity_ready() is False
            seed_markers(server)
            assert await repository.family_identity_ready() is True
            assert await repository.ready() is True
            server.records[COLLECTIONS["schema"]].pop("pc02-family-identity")
            assert await repository.family_identity_ready() is False
            assert await repository.ready() is True
        assert all(request.method == "GET" for request in server.requests)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, json={}),
        httpx.Response(500, json={}),
        httpx.Response(200, json={"total": True}),
        httpx.Response(200, json={"total": -1}),
    ],
)
def test_partial_or_unavailable_new_collection_leaves_features_disabled(response):
    async def scenario():
        server = FamilyDocumentServer()
        seed_markers(server)

        def transport(request):
            return response if "/sc_v2_parent_profiles/" in request.url.path else server(request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            assert await CloudBaseDocumentRepository(WIRE_SETTINGS, client).family_identity_ready() is False

    asyncio.run(scenario())


def test_cloudbase_first_profile_save_converges_and_never_changes_private_user():
    async def scenario():
        server = FamilyDocumentServer()
        initial_reads = 0
        barrier = asyncio.Event()

        async def transport(request):
            nonlocal initial_reads
            response = server(request)
            if request.method == "GET" and "/sc_v2_parent_profiles/" in request.url.path:
                initial_reads += 1
                if initial_reads <= 12:
                    if initial_reads == 12:
                        barrier.set()
                    await barrier.wait()
            return response

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            repository = CloudBaseDocumentRepository(WIRE_SETTINGS, client)
            profiles = await asyncio.gather(
                *(repository.save_parent_profile("synthetic-owner-a", "合成昵称") for _ in range(12))
            )
            assert len({item["id"] for item in profiles}) == 1
            assert len({item["created_at"] for item in profiles}) == 1
            assert len(server.records[COLLECTIONS["parent_profiles"]]) == 1
            original = profiles[0]
            changed = await repository.save_parent_profile("synthetic-owner-a", "新合成昵称")
            assert changed["id"] == original["id"] and changed["created_at"] == original["created_at"]
            assert changed["nickname"] == "新合成昵称"
            assert await repository.get_parent_profile("synthetic-owner-b") is None
        assert not server.records[COLLECTIONS["users"]]
        assert not server.records[COLLECTIONS["identities"]]
        assert not server.records[COLLECTIONS["children"]]
        for request in server.requests:
            assert "/sc_v2_parent_profiles/" in request.url.path
            if request.method == "GET":
                assert "owner_user_id" in json.loads(request.url.params["query"])
            elif request.method == "PATCH":
                assert json.loads(request.content)["query"]["owner_user_id"] == "synthetic-owner-a"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"insertedIds": []}),
        httpx.Response(201, json={"insertedIds": ["wrong-id"]}),
        httpx.Response(500, json={}),
    ],
)
def test_parent_profile_write_cannot_claim_unconfirmed_save(response):
    async def scenario():
        server = FamilyDocumentServer()

        def transport(request):
            return response if request.method == "POST" else server(request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            with pytest.raises(CloudError) as error:
                await CloudBaseDocumentRepository(WIRE_SETTINGS, client).save_parent_profile(
                    "synthetic-owner-a", "合成昵称"
                )
            assert error.value.status == 503
        assert not server.records[COLLECTIONS["parent_profiles"]]

    asyncio.run(scenario())


def test_cross_owner_profile_response_fails_closed():
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"list": [{"owner_user_id": "other-owner", "nickname": "不可读取"}]})
            )
        ) as client:
            with pytest.raises(CloudError) as error:
                await CloudBaseDocumentRepository(WIRE_SETTINGS, client).get_parent_profile("synthetic-owner-a")
            assert error.value.status == 503

    asyncio.run(scenario())


def test_cloudbase_optional_child_age_writes_are_additive_and_owner_scoped():
    async def scenario():
        server = FamilyDocumentServer()
        seed_markers(server)
        original_marker = deepcopy(server.records[COLLECTIONS["schema"]]["phase04"])
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
            repository = CloudBaseDocumentRepository(WIRE_SETTINGS, client)
            service = ApplicationService(repository)
            first = await service.resolve_user(AppPrincipal("synthetic-child-owner-a", WIRE_SETTINGS.env_id))
            second = await service.resolve_user(AppPrincipal("synthetic-child-owner-b", WIRE_SETTINGS.env_id))
            child = await service.create_child(first, ChildWrite(nickname="私有合成昵称", age_band="13-15"))
            stored = server.records[COLLECTIONS["children"]][str(child.id)]
            assert stored["age_band"] == "13-15"
            assert (await service.update_child(first, child.id, ChildWrite(nickname="修改昵称"))).age_band == "13-15"
            assert (
                await service.update_child(first, child.id, ChildWrite(nickname="修改昵称", age_band=None))
            ).age_band is None
            with pytest.raises(CloudError) as error:
                await service.update_child(second, child.id, ChildWrite(nickname="越权修改", age_band="0-2"))
            assert error.value.status == 404
            stored.pop("age_band")
            assert (await service.child(first, child.id)).age_band is None
        assert server.records[COLLECTIONS["schema"]]["phase04"] == original_marker
        for request in server.requests:
            if "/sc_v2_child_profiles/" in request.url.path and request.method in {"PATCH", "GET"}:
                query = (
                    json.loads(request.content)["query"]
                    if request.method == "PATCH"
                    else json.loads(request.url.params["query"])
                )
                assert "owner_user_id" in query
            if "/sc_v2_app_schema/" in request.url.path:
                assert request.method == "GET"

    asyncio.run(scenario())


def test_parent_profile_put_has_bounded_h5_cors_preflight():
    settings = Settings(allowed_origins=("https://client.example.test",))
    with TestClient(create_app(settings, InMemoryRepository(), FamilyVerifier())) as client:
        response = client.options(
            "/api/v2/parent-profile",
            headers={
                "Origin": "https://client.example.test",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert response.status_code == 204
        assert "PUT" in response.headers["Access-Control-Allow-Methods"]
