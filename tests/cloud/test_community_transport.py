"""PC03 official REST shapes and uncertainty; all data and credentials synthetic."""

import asyncio
from copy import deepcopy
import json
from threading import RLock
from uuid import uuid4

import httpx
import pytest

from cloud.api.soulcompanion_cloud.config import Settings
from cloud.api.soulcompanion_cloud.errors import CloudError
from cloud.api.soulcompanion_cloud.repository import COLLECTIONS, CloudBaseDocumentRepository
from cloud.api.soulcompanion_cloud.community.repository import (
    CommunityDocumentRepository, InMemoryCommunityRepository, matches,
)
from cloud.api.soulcompanion_cloud.community.schema import (
    COMMUNITY_BASE_MARKERS, COMMUNITY_COLLECTIONS, COMMUNITY_MARKER_ID,
    COMMUNITY_SCHEMA_CHECKSUM, COMMUNITY_SCHEMA_OWNER, COMMUNITY_SCHEMA_VERSION, SCHEMA_COLLECTION,
)


SETTINGS = Settings(env_id="synthetic-community-env", api_key="synthetic-community-server-key")


def evaluate(document, query):
    """Fake database supports the documented subset, independent of adapter validation."""
    for field, value in query.items():
        if field == "$or":
            assert isinstance(value, list) and len(value) == 2
            if not any(evaluate(document, condition) for condition in value):
                return False
        elif isinstance(value, dict):
            assert len(value) == 1
            operator, operand = next(iter(value.items()))
            if operator == "$in":
                if document.get(field) not in operand:
                    return False
            elif operator == "$lt":
                if document.get(field) is None or document[field] >= operand:
                    return False
            else:
                raise AssertionError("Unsupported database operator")
        elif document.get(field) != value:
            return False
    return True


class CommunityWireServer:
    def __init__(self):
        self.records = {name: {} for name in (*COMMUNITY_COLLECTIONS.values(), *COLLECTIONS.values())}
        expected = (*COMMUNITY_BASE_MARKERS,
                    (COMMUNITY_MARKER_ID, COMMUNITY_SCHEMA_OWNER, COMMUNITY_SCHEMA_CHECKSUM, COMMUNITY_SCHEMA_VERSION))
        for marker, owner, checksum, version in expected:
            self.records[SCHEMA_COLLECTION][marker] = {"_id": marker, "owner": owner, "checksum": checksum, "version": version}
        self.requests = []
        self.lock = RLock()

    def __call__(self, request):
        with self.lock:
            self.requests.append(request)
            assert request.headers["authorization"] == f"Bearer {SETTINGS.api_key}"
            assert request.url.host == "synthetic-community-env.api.tcloudbasegateway.com"
            assert request.url.path.startswith("/v1/database/instances/(default)/databases/(default)/collections/")
            collection = request.url.path.split("/collections/", 1)[1].split("/", 1)[0]
            records = self.records[collection]
            if request.method == "GET":
                assert request.url.params["offset"] == "0"
                limit = int(request.url.params["limit"])
                assert 1 <= limit <= 51
                rows = [deepcopy(record) for record in records.values() if evaluate(record, json.loads(request.url.params["query"]))]
                if "order" in request.url.params:
                    order = json.loads(request.url.params["order"])
                    assert len(order) == 2 and order[1] == {"id": "desc"}
                    field = next(iter(order[0]))
                    assert order[0][field] == "desc"
                    rows.sort(key=lambda row: (row[field], row["id"]), reverse=True)
                return httpx.Response(200, json={"list": rows[:limit]})
            body = json.loads(request.content)
            if request.method == "POST":
                assert set(body) == {"data"} and len(body["data"]) == 1
                record = body["data"][0]
                if record["_id"] in records:
                    return httpx.Response(500, json={"message": "synthetic-private-provider-error"})
                records[record["_id"]] = deepcopy(record)
                return httpx.Response(201, json={"insertedIds": [record["_id"]]})
            assert request.method == "PATCH"
            assert body["multi"] is False and body["upsert"] is False and body["replaceMode"] is False
            assert set(body["data"]) == {"$set"}
            selected = [record for record in records.values() if evaluate(record, body["query"])]
            assert len(selected) <= 1
            for record in selected:
                record.update(deepcopy(body["data"]["$set"]))
            return httpx.Response(200, json={"matched": len(selected), "updated": len(selected)})


def record(**fields):
    identifier = str(uuid4())
    return {"_id": identifier, "id": identifier, "owner_id": str(uuid4()),
            "row_version": 1, "created_at": "2026-10-10T00:00:00.000000Z", **fields}


def run_with_server(scenario, server=None, handler=None):
    server = server or CommunityWireServer()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler or server)) as client:
            repository = CommunityDocumentRepository(CloudBaseDocumentRepository(SETTINGS, client))
            await scenario(repository, server)
    asyncio.run(run())
    return server


def test_readiness_batch_is_read_only_and_exact_without_private_queries():
    async def scenario(repo, server):
        assert await repo.ready() is True
        assert len(server.requests) == 1
        request = server.requests[0]
        assert request.method == "GET"
        assert SCHEMA_COLLECTION in request.url.path
        assert set(json.loads(request.url.params["query"])["_id"]["$in"]) == {row[0] for row in COMMUNITY_BASE_MARKERS} | {COMMUNITY_MARKER_ID}
    run_with_server(scenario)


@pytest.mark.parametrize("marker", [row[0] for row in COMMUNITY_BASE_MARKERS] + [COMMUNITY_MARKER_ID])
@pytest.mark.parametrize("field,value", [("owner", "foreign"), ("checksum", "wrong"), ("version", 0), ("version", True), ("_id", "wrong")])
def test_bad_dependency_or_incremental_marker_disables_community(marker, field, value):
    server = CommunityWireServer()
    server.records[SCHEMA_COLLECTION][marker][field] = value
    async def scenario(repo, _):
        assert await repo.ready() is False
    run_with_server(scenario, server)


def test_canonical_insert_replay_conflicting_input_and_atomic_cas():
    async def scenario(repo, server):
        candidate = record(kind="post", initial_payload_hash="a" * 64)
        immutable = {field: candidate[field] for field in ("_id", "id", "owner_id", "initial_payload_hash")}
        first, created = await repo.insert("content", candidate, immutable)
        assert created and first == candidate
        replay, created = await repo.insert("content", candidate, immutable)
        assert not created and replay == candidate
        with pytest.raises(CloudError) as error:
            await repo.insert("content", {**candidate, "initial_payload_hash": "b" * 64}, {**immutable, "initial_payload_hash": "b" * 64})
        assert error.value.status == 409
        expected = {"_id": candidate["id"], "owner_id": candidate["owner_id"], "row_version": 1}
        assert await repo.cas("content", candidate["id"], expected, {"row_version": 2})
        assert not await repo.cas("content", candidate["id"], expected, {"row_version": 3})
        assert (await repo.get("content", candidate["id"]))["row_version"] == 2
        assert len(server.records[COMMUNITY_COLLECTIONS["content"]]) == 1
    run_with_server(scenario)


def test_pagination_uses_bounded_or_lt_and_two_sort_fields():
    async def scenario(repo, server):
        rows = [record(kind="post", status="published", published_at="2026-10-10T00:00:00.000000Z") for _ in range(7)]
        server.records[COMMUNITY_COLLECTIONS["content"]] = {row["id"]: row for row in rows}
        first = await repo.list("content", {"kind": "post", "status": "published"}, "published_at", 3)
        edge = first[-1]
        query = {"kind": "post", "status": "published", "$or": [
            {"published_at": {"$lt": edge["published_at"]}},
            {"published_at": edge["published_at"], "id": {"$lt": edge["id"]}},
        ]}
        rest = await repo.list("content", query, "published_at", 51)
        assert [row["id"] for row in first + rest] == sorted([row["id"] for row in rows], reverse=True)
        assert len({row["id"] for row in first + rest}) == 7
        batch = await repo.list("content", {"id": {"$in": [rows[0]["id"], rows[1]["id"]]}, "status": "published"}, "published_at", 2)
        assert {row["id"] for row in batch} == {rows[0]["id"], rows[1]["id"]}
    run_with_server(scenario)


@pytest.mark.parametrize("ack", [{}, {"matched": True, "updated": True}, {"matched": 1, "updated": 0}, {"matched": 0, "updated": 1}, {"matched": 2, "updated": 2}])
def test_cas_never_claims_success_for_ambiguous_ack(ack):
    server = CommunityWireServer()
    def handler(request):
        return httpx.Response(200, json=ack) if request.method == "PATCH" else server(request)
    async def scenario(repo, _):
        candidate = record()
        with pytest.raises(CloudError) as error:
            await repo.cas("content", candidate["id"], {"_id": candidate["id"]}, {"row_version": 2})
        assert error.value.status == 503
    run_with_server(scenario, server, handler)


@pytest.mark.parametrize("response", [httpx.Response(201, json={"insertedIds": []}), httpx.Response(500, json={}), httpx.Response(409, json={})])
def test_no_canonical_record_means_no_insert_success(response):
    server = CommunityWireServer()
    def handler(request):
        return response if request.method == "POST" else server(request)
    async def scenario(repo, _):
        candidate = record()
        with pytest.raises(CloudError) as error:
            await repo.insert("content", candidate, {"_id": candidate["id"], "owner_id": candidate["owner_id"]})
        assert error.value.status == 503
    run_with_server(scenario, server, handler)


def test_committed_cas_with_lost_ack_is_unconfirmed_not_false_success():
    server = CommunityWireServer()
    candidate = record()
    server.records[COMMUNITY_COLLECTIONS["content"]][candidate["id"]] = candidate
    def handler(request):
        response = server(request)
        if request.method == "PATCH":
            raise httpx.ReadTimeout("synthetic-private-provider-error", request=request)
        return response
    async def scenario(repo, _):
        with pytest.raises(CloudError) as error:
            await repo.cas("content", candidate["id"], {"_id": candidate["id"], "row_version": 1}, {"row_version": 2})
        assert error.value.status == 503 and "synthetic-private" not in str(error.value)
        assert (await repo.get("content", candidate["id"]))["row_version"] == 2
    run_with_server(scenario, server, handler)


def test_distributed_quota_two_adapters_share_one_canonical_record_and_limit():
    async def scenario(repo, server):
        second = CommunityDocumentRepository(repo.transport)
        owner = str(uuid4())
        for index in range(10):
            await (repo if index % 2 else second).consume_quota(owner, "post")
        with pytest.raises(CloudError) as error:
            await second.consume_quota(owner, "post")
        assert error.value.status == 429
        quotas = server.records[COMMUNITY_COLLECTIONS["write_quotas"]]
        assert len(quotas) == 1 and next(iter(quotas.values()))["used"] == 10
        await repo.consume_quota(str(uuid4()), "post")
        assert len(quotas) == 2
    run_with_server(scenario)


def test_quota_contention_is_bounded_and_cannot_exceed_quota():
    class CompetingStore(InMemoryCommunityRepository):
        async def cas(self, kind, identifier, expected, changes):
            if kind == "write_quotas":
                return False
            return await super().cas(kind, identifier, expected, changes)
    async def scenario():
        store = CompetingStore()
        with pytest.raises(CloudError) as error:
            await store.consume_quota(str(uuid4()), "post")
        assert error.value.status == 503
        assert next(iter(store.records["write_quotas"].values()))["used"] == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("query", [{"x": {"$gt": "a"}}, {"$where": "evil"}, {"x": {"$in": list(range(52))}}, {"$or": []}])
def test_unknown_or_unbounded_internal_operators_fail_closed(query):
    with pytest.raises(CloudError) as error:
        matches({"x": "b"}, query)
    assert error.value.status == 503


def test_query_validation_cannot_be_skipped_by_nonmatching_first_field_or_empty_database():
    query = {"id": "nonmatching", "bad": {"$where": "anything"}}
    with pytest.raises(CloudError):
        matches({"id": "other"}, query)
    async def scenario(repo, server):
        with pytest.raises(CloudError):
            await repo.list("content", query, "created_at", 1)
        assert not server.requests
        identifier = str(uuid4())
        with pytest.raises(CloudError):
            await repo.cas("content", identifier, {"_id": identifier, "bad": {"$where": "anything"}}, {"row_version": 2})
        assert not server.requests
    run_with_server(scenario)


def test_full_api_workflow_uses_production_community_and_family_rest_adapters():
    from fastapi.testclient import TestClient
    from cloud.api.soulcompanion_cloud.app import create_app
    from cloud.api.soulcompanion_cloud.auth import AppPrincipal
    from cloud.api.soulcompanion_cloud.family_identity import parent_profile_id
    from cloud.api.soulcompanion_cloud.repository import identity_records
    from scripts.cloud_community_roles import RoleManager

    server = CommunityWireServer()
    principals = {"wire-author": AppPrincipal("synthetic-wire-author", SETTINGS.env_id),
                  "wire-moderator": AppPrincipal("synthetic-wire-moderator", SETTINGS.env_id)}
    users = {}
    for token, principal in principals.items():
        user, identity = identity_records(principal)
        server.records[COLLECTIONS["users"]][user["id"]] = user
        server.records[COLLECTIONS["identities"]][identity["id"]] = identity
        users[token] = user["id"]
    owner = users["wire-author"]
    public_id = parent_profile_id(owner)
    at = "2026-10-10T00:00:00.000000Z"
    server.records[COLLECTIONS["parent_profiles"]][public_id] = {
        "_id": public_id, "id": public_id, "owner_user_id": owner, "nickname": "合成接口家长",
        "created_at": at, "updated_at": at,
    }
    class VerifiedSyntheticTokens:
        async def verify(self, token):
            if token not in principals:
                raise CloudError(401, "unauthorized", "Please sign in again.")
            return principals[token]

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(server))
    family = CloudBaseDocumentRepository(SETTINGS, upstream)
    community = CommunityDocumentRepository(family)
    async def lookup(principal):
        return server.records[COLLECTIONS["users"]].get(principal)
    from scripts.cloud_community_roles import ENV_ID, REGION
    from scripts.cloud_community_target import DATABASE_ID
    preflight = lambda: {"env_id": ENV_ID, "region": REGION, "package_id": "baas_trial",
                         "overrun": False, "auto_renew": False, "database_id": DATABASE_ID}
    actual_environment = lambda: {"EnvInfo": {"EnvBaseInfo": {
        "EnvId": ENV_ID, "Region": REGION, "Status": "NORMAL",
        "Databases": [{"InstanceId": DATABASE_ID, "Status": "RUNNING"}],
    }}}
    asyncio.run(RoleManager(community, lookup, preflight, actual_environment).change(users["wire-moderator"], "grant",
        "合成本地审核链路", "synthetic-role-key", cloud_write_authorized=True))
    headers = {"Authorization": "Bearer wire-author", "Idempotency-Key": "synthetic-post-key"}
    review_headers = {"Authorization": "Bearer wire-moderator", "Idempotency-Key": "synthetic-approve-key"}
    with TestClient(create_app(SETTINGS, family, VerifiedSyntheticTokens(), community)) as api:
        created = api.post("/api/v2/community/posts", headers=headers, json={
            "title": "合成接口链路", "body": "纯文本合成内容", "age_band": "6-8", "topic": "parent-child",
        })
        assert created.status_code == 201 and created.json()["status"] == "pending"
        identifier = created.json()["id"]
        assert api.get("/api/v2/community/posts").json()["items"] == []
        approved = api.post(f"/api/v2/ops/moderation/posts/{identifier}/approve", headers=review_headers,
                            json={"expected_revision": 1, "reason": "合成内容人工核验"})
        assert approved.status_code == 200 and approved.json()["content"]["status"] == "published"
        public = api.get(f"/api/v2/community/posts/{identifier}")
        assert public.status_code == 200 and public.json()["author"] == {"id": public_id, "nickname": "合成接口家长"}
        assert owner not in public.text and "synthetic-wire-author" not in public.text
        for kind in ("like", "bookmark"):
            path = f"/api/v2/community/posts/{identifier}/{kind}"
            assert api.put(path, headers=headers, json={}).status_code == 200
            assert api.put(path, headers=headers, json={}).json()["active"] is True
        comment = api.post(f"/api/v2/community/posts/{identifier}/comments", headers=headers, json={"body": "合成一级评论"})
        assert comment.status_code == 201
        comment_id = comment.json()["id"]
        assert api.get(f"/api/v2/community/comments/{comment_id}").status_code == 404
        assert api.post(f"/api/v2/ops/moderation/comments/{comment_id}/approve", headers=review_headers,
                        json={"expected_revision": 1, "reason": "合成评论人工核验"}).status_code == 200
        assert api.get(f"/api/v2/community/comments/{comment_id}").status_code == 200
        report = api.post("/api/v2/community/content-reports", headers=headers,
                          json={"target_type": "post", "target_id": identifier, "reason": "privacy", "detail": "合成举报说明"})
        assert report.status_code == 201
        assert api.post(f"/api/v2/ops/content-reports/{report.json()['id']}/resolve", headers=review_headers,
                        json={"expected_revision": 1, "decision": "resolved", "reason": "合成处理记录"}).status_code == 200
        assert api.get(f"/api/v2/community/posts/{identifier}").status_code == 200
        assert api.post(f"/api/v2/ops/moderation/posts/{identifier}/hide", headers=review_headers,
                        json={"expected_revision": 1, "reason": "合成隐藏验证"}).status_code == 200
        assert api.get(f"/api/v2/community/comments/{comment_id}").status_code == 404
        assert api.get("/api/v2/me/community/bookmarks", headers=headers).json()["items"] == []
        assert api.delete(f"/api/v2/community/posts/{identifier}", headers=headers, params={"expected_revision": 1}).status_code == 204
    asyncio.run(upstream.aclose())
    forbidden = {COLLECTIONS[kind] for kind in ("children", "sessions", "emotions", "reports")}
    assert all(not any(f"/collections/{name}/" in request.url.path for name in forbidden) for request in server.requests)


@pytest.mark.parametrize("limit", [0, 52, True])
def test_query_limits_enforced_by_adapter_before_http(limit):
    async def scenario(repo, server):
        with pytest.raises(CloudError):
            await repo.list("content", {}, "created_at", limit)
        assert not server.requests
    run_with_server(scenario)
