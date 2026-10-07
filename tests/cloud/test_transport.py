"""Official HTTP wire contracts and failure safety with deterministic mock transports."""

import asyncio
from datetime import datetime, timezone
import json
from uuid import uuid4

import httpx
import pytest

from cloud.api.soulcompanion_cloud.auth import AppPrincipal, CloudBaseTokenVerifier
from cloud.api.soulcompanion_cloud.config import Settings
from cloud.api.soulcompanion_cloud.errors import CloudError
from cloud.api.soulcompanion_cloud.repository import (
    COLLECTIONS,
    CloudBaseDocumentRepository,
    decode_ejson,
    identity_records,
)


CONFIG = Settings(env_id="test-cloudbase-env", api_key="synthetic-server-api-key")


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.mark.parametrize(
    "status,data,expected",
    [
        (200, {}, 401),
        (401, {}, 401),
        (403, {}, 401),
        (500, {"message": "synthetic-secret"}, 503),
        (200, [], 503),
        (200, {"sub": "a", "token_type": "Bearer", "client_id": "other-env"}, 401),
        (200, {"sub": "", "token_type": "Bearer", "client_id": CONFIG.env_id}, 401),
        (200, {"uid": "a", "token_type": "Bearer", "client_id": CONFIG.env_id}, 401),
        (200, {"sub": "a", "token_type": "Refresh", "client_id": CONFIG.env_id}, 401),
        (200, {"sub": "a", "token_type": [], "client_id": CONFIG.env_id}, 401),
        (200, {"sub": "a", "token_type": 42, "client_id": CONFIG.env_id}, 401),
        (200, {"sub": "a", "token_type": None, "client_id": CONFIG.env_id}, 401),
    ],
)
def test_introspection_rejects_invalid_revoked_wrong_environment_and_failures(
    status, data, expected
):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(status, json=data))
        ) as client:
            verifier = CloudBaseTokenVerifier(CONFIG, client)
            with pytest.raises(CloudError) as error:
                await verifier.verify("synthetic-token")
            assert error.value.status == expected
            assert "synthetic-secret" not in str(error.value)

    run(scenario())


def test_introspection_uses_exact_official_endpoint_and_server_verified_subject():
    def handler(request):
        assert request.method == "GET"
        assert (
            str(request.url)
            == "https://test-cloudbase-env.api.tcloudbasegateway.com/auth/v1/token/introspect"
        )
        assert request.headers["Authorization"] == "Bearer synthetic-user-access-token"
        return httpx.Response(
            200,
            json={
                "sub": "verified-subject",
                "client_id": CONFIG.env_id,
                "token_type": "Bearer",
                "scope": "user sso",
            },
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            principal = await CloudBaseTokenVerifier(CONFIG, client).verify(
                "synthetic-user-access-token"
            )
            assert (
                principal.subject == "verified-subject"
                and principal.provider == "cloudbase_auth"
            )
            assert "verified-subject" not in repr(principal)

    run(scenario())


def test_introspection_timeout_and_malformed_json_fail_closed():
    for handler in [
        lambda _: httpx.Response(200, text="not-json"),
        lambda request: (_ for _ in ()).throw(
            httpx.ReadTimeout("synthetic-token", request=request)
        ),
    ]:

        async def scenario():
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ) as client:
                with pytest.raises(CloudError) as error:
                    await CloudBaseTokenVerifier(CONFIG, client).verify(
                        "synthetic-token"
                    )
                assert error.value.status == 503 and "synthetic-token" not in str(
                    error.value
                )

        run(scenario())


def test_settings_secrets_are_not_represented_and_cors_rejects_wildcards():
    assert "synthetic-server-api-key" not in repr(CONFIG)
    for origin in [
        "*",
        "https://*.example.test",
        "http://example.test",
        "https://example.test/path",
        "https://user:password@example.test",
    ]:
        with pytest.raises(ValueError):
            Settings(allowed_origins=(origin,))


def test_identity_keys_converge_only_for_same_verified_identity():
    first = identity_records(AppPrincipal("verified-user", "env-a"))
    second = identity_records(AppPrincipal("verified-user", "env-a"))
    assert first[0]["id"] == second[0]["id"] and first[1]["id"] == second[1]["id"]
    assert (
        first[0]["id"]
        != identity_records(AppPrincipal("verified-user", "env-b"))[0]["id"]
    )
    assert (
        first[0]["id"] != identity_records(AppPrincipal("other-user", "env-a"))[0]["id"]
    )


def test_strict_ejson_metadata_scalars():
    assert decode_ejson(
        {
            "count": {"$numberLong": "65"},
            "score": {"$numberDouble": "0.75"},
            "created": {"$date": {"$numberLong": "0"}},
        }
    ) == {"count": 65, "score": 0.75, "created": "1970-01-01T00:00:00Z"}
    with pytest.raises(ValueError):
        decode_ejson({"$numberDouble": "NaN"})


class DocumentServer:
    """Wire fake which implements only official collection operations used by the adapter."""

    def __init__(self):
        self.records = {collection: {} for collection in COLLECTIONS.values()}
        self.requests = []

    def __call__(self, request):
        assert request.headers["Authorization"] == "Bearer synthetic-server-api-key"
        assert request.url.host == "test-cloudbase-env.api.tcloudbasegateway.com"
        assert request.url.path.startswith(
            "/v1/database/instances/(default)/databases/(default)/collections/"
        )
        self.requests.append(request)
        suffix = request.url.path.split("/collections/", 1)[1].split("/")
        records = self.records[suffix[0]]
        body = json.loads(request.content) if request.content else {}
        if len(suffix) == 3:
            record_id = suffix[2]
            if request.method == "PATCH":
                assert body["upsert"] is True and body["replaceMode"] is False
                records.setdefault(record_id, body["data"]["$setOnInsert"])
                return httpx.Response(200, json={"matched": 1, "updated": 0})
            return (
                httpx.Response(200, json=records[record_id])
                if record_id in records
                else httpx.Response(404, json={})
            )
        if request.method == "POST":
            for record in body["data"]:
                assert record["_id"] not in records
                records[record["_id"]] = record
            return httpx.Response(
                201, json={"insertedIds": [record["_id"] for record in body["data"]]}
            )
        query = (
            body.get("query")
            if request.method == "PATCH"
            else json.loads(request.url.params.get("query", "{}"))
        )
        selected = [
            record
            for record in records.values()
            if all(record.get(key) == value for key, value in query.items())
        ]
        if request.method == "PATCH":
            assert body["upsert"] is False and body["multi"] is False
            for record in selected[:1]:
                record.update(body["data"]["$set"])
            return httpx.Response(
                200, json={"matched": len(selected[:1]), "updated": len(selected[:1])}
            )
        if request.url.params.get("count") == "true":
            return httpx.Response(200, json={"total": len(selected)})
        limit, offset = int(request.url.params.get("limit", "20")), int(
            request.url.params.get("offset", "0")
        )
        return httpx.Response(
            200,
            json={
                "list": selected[offset : offset + limit],
                "offset": offset,
                "limit": limit,
            },
        )


def test_cloudbase_repository_concurrent_identity_crud_and_all_owner_filters():
    async def scenario():
        server = DocumentServer()
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
            repository = CloudBaseDocumentRepository(CONFIG, client)
            users = await asyncio.gather(
                *(
                    repository.resolve_user(AppPrincipal("synthetic-a", CONFIG.env_id))
                    for _ in range(12)
                )
            )
            user = users[0]
            assert len({item["id"] for item in users}) == 1
            assert len(server.records[COLLECTIONS["users"]]) == 1
            assert len(server.records[COLLECTIONS["identities"]]) == 1
            assert (
                await repository.update_user(user["id"], {"display_name": "changed"})
            )["display_name"] == "changed"
            assert (
                await repository.resolve_user(
                    AppPrincipal("synthetic-a", CONFIG.env_id)
                )
            )["display_name"] == "changed"
            for kind in ("children", "sessions", "emotions", "reports"):
                record = {
                    "id": str(uuid4()),
                    "created_at": "2026-10-07T00:00:00.000000Z",
                    "timestamp": "2026-10-07T00:00:00.000000Z",
                    "range_end": "2026-10-07T00:00:00.000000Z",
                    "status": "active",
                }
                await repository.create_owned(kind, record, user["id"])
                assert (await repository.get_owned(kind, record["id"], user["id"]))[
                    "id"
                ] == record["id"]
                assert (await repository.list_owned(kind, user["id"], {}, 20, 0))[
                    1
                ] == 1
                assert (
                    await repository.list_owned(kind, "different-owner", {}, 20, 0)
                )[1] == 0
                with pytest.raises(CloudError) as error:
                    await repository.get_owned(kind, record["id"], "different-owner")
                assert error.value.status == 404
                with pytest.raises(CloudError):
                    await repository.update_owned(
                        kind, record["id"], "different-owner", {"status": "hijacked"}
                    )
                assert (
                    await repository.update_owned(
                        kind,
                        record["id"],
                        user["id"],
                        {"status": "ended"},
                        {"status": "active"},
                    )
                )["status"] == "ended"
                assert (
                    await repository.update_owned(
                        kind,
                        record["id"],
                        user["id"],
                        {"status": "other"},
                        {"status": "active"},
                    )
                )["status"] == "ended"
            for request in server.requests:
                if any(
                    f"/{COLLECTIONS[kind]}/" in request.url.path
                    for kind in ("children", "sessions", "emotions", "reports")
                ):
                    if request.method == "GET":
                        assert "owner_user_id" in json.loads(
                            request.url.params["query"]
                        )
                    elif request.method == "PATCH":
                        assert "owner_user_id" in json.loads(request.content)["query"]

    run(scenario())


def test_readiness_requires_key_schema_and_all_collections():
    async def scenario():
        server = DocumentServer()
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
            assert (
                await CloudBaseDocumentRepository(
                    Settings(env_id=CONFIG.env_id), client
                ).ready()
                is False
            )
            repository = CloudBaseDocumentRepository(CONFIG, client)
            assert await repository.ready() is False
            server.records[COLLECTIONS["schema"]]["phase04"] = {
                "_id": "phase04",
                "version": 1,
            }
            assert await repository.ready() is True
            server.records[COLLECTIONS["schema"]]["phase04"]["version"] = 2
            assert await repository.ready() is False

    run(scenario())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, json={"message": "synthetic-server-api-key"}),
        httpx.Response(500, json={}),
        httpx.Response(
            200, json={"list": [{"id": "wrong-owner", "owner_user_id": "other"}]}
        ),
        httpx.Response(200, text="not-json"),
    ],
)
def test_repository_failure_and_unexpected_cross_owner_response_fail_closed(response):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: response)
        ) as client:
            with pytest.raises(CloudError) as error:
                await CloudBaseDocumentRepository(CONFIG, client).get_owned(
                    "children", "synthetic-id", "right-owner"
                )
            assert error.value.status == 503 and "synthetic-server-api-key" not in str(
                error.value
            )

    run(scenario())


def test_repository_rejects_http200_silent_write_failure():
    async def scenario():
        server = DocumentServer()
        record_id, owner = str(uuid4()), str(uuid4())
        server.records[COLLECTIONS["children"]][record_id] = {
            "_id": record_id,
            "id": record_id,
            "owner_user_id": owner,
            "nickname": "unchanged",
        }
        for acknowledgment in [
            {},
            {"code": "DATABASE_ERROR"},
            {"matched": 0, "updated": 0},
            {"matched": 1, "updated": 0},
        ]:

            def transport(request):
                return (
                    httpx.Response(200, json=acknowledgment)
                    if request.method == "PATCH"
                    else server(request)
                )

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(transport)
            ) as client:
                with pytest.raises(CloudError) as error:
                    await CloudBaseDocumentRepository(CONFIG, client).update_owned(
                        "children", record_id, owner, {"nickname": "new"}
                    )
                assert error.value.status == 503

    run(scenario())


@pytest.mark.parametrize(
    "acknowledgment",
    [
        {"matched": 0, "updated": 0},
        {"matched": 0, "updated": 0, "upsert_id": "wrong-identity"},
        {"code": "SILENT_FAILURE"},
    ],
)
def test_existing_user_does_not_hide_missing_identity_write(acknowledgment):
    async def scenario():
        server = DocumentServer()
        principal = AppPrincipal("synthetic-partial-first-request", CONFIG.env_id)
        user, identity = identity_records(principal)
        server.records[COLLECTIONS["users"]][user["id"]] = user

        def transport(request):
            if (
                request.method == "PATCH"
                and f"/{COLLECTIONS['identities']}/" in request.url.path
            ):
                return httpx.Response(200, json=acknowledgment)
            return server(request)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        ) as client:
            with pytest.raises(CloudError) as error:
                await CloudBaseDocumentRepository(CONFIG, client).resolve_user(
                    principal
                )
            assert error.value.status == 503
            assert not server.records[COLLECTIONS["identities"]]

    run(scenario())


def test_valid_insert_acknowledgment_is_accepted_for_new_identity():
    async def scenario():
        server = DocumentServer()
        principal = AppPrincipal("synthetic-new-request", CONFIG.env_id)
        user, identity = identity_records(principal)

        def transport(request):
            response = server(request)
            if request.method == "PATCH":
                return httpx.Response(
                    200,
                    json={
                        "matched": 0,
                        "updated": 0,
                        "upsert_id": request.url.path.rsplit("/", 1)[1],
                    },
                )
            return response

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        ) as client:
            assert (
                await CloudBaseDocumentRepository(CONFIG, client).resolve_user(
                    principal
                )
            )["id"] == user["id"]
            assert identity["id"] in server.records[COLLECTIONS["identities"]]

    run(scenario())
