"""Cloud v2 contract and authorization tests; no CloudBase credentials are used."""

from concurrent.futures import ThreadPoolExecutor
import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from cloud.api.soulcompanion_cloud.app import create_app
from cloud.api.soulcompanion_cloud.auth import AppPrincipal
from cloud.api.soulcompanion_cloud.config import Settings
from cloud.api.soulcompanion_cloud.errors import CloudError
from cloud.api.soulcompanion_cloud.repository import InMemoryRepository
from cloud.api.soulcompanion_cloud.models import ChildWrite, SessionCreate
from cloud.api.soulcompanion_cloud.service import ApplicationService


class TestVerifier:
    __test__ = False

    async def verify(self, token):
        if token not in {"test-user-a", "test-user-b"}:
            raise CloudError(401, "unauthorized", "Please sign in again.")
        return AppPrincipal(subject=token, issuer="test-environment")

    async def ready(self):
        return True


@pytest.fixture
def repository():
    return InMemoryRepository()


@pytest.fixture
def client(repository):
    settings = Settings(
        allowed_origins=("https://client.example.test",), private_rate_limit=200
    )
    with TestClient(create_app(settings, repository, TestVerifier())) as value:
        yield value


def auth(user="a"):
    return {"Authorization": f"Bearer test-user-{user}"}


def create_child(client, user="a", nickname="小朋友"):
    response = client.post(
        "/api/v2/children", headers=auth(user), json={"nickname": nickname}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health_readiness_and_response_metadata(client):
    for endpoint, expected in [("healthz", "ok"), ("readyz", "healthy")]:
        response = client.get(f"/api/v2/{endpoint}")
        assert response.status_code == 200
        assert response.json() == {"status": expected}
        UUID(response.headers["X-Request-ID"])
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize(
    "path", ["me", "children", "sessions", "emotions", "reports", "reports/current"]
)
@pytest.mark.parametrize(
    "headers", [{}, {"x-wx-openid": "spoof"}, {"Authorization": "Bearer expired"}]
)
def test_private_routes_reject_missing_spoofed_and_expired_auth(client, path, headers):
    response = client.get(f"/api/v2/{path}", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "expired" not in response.text and "spoof" not in response.text


def test_user_identity_is_opaque_stable_and_concurrent(client, repository):
    with ThreadPoolExecutor(max_workers=8) as executor:
        users = list(
            executor.map(
                lambda _: client.get("/api/v2/me", headers=auth()).json(), range(20)
            )
        )
    assert len({item["id"] for item in users}) == 1
    UUID(users[0]["id"])
    assert "subject" not in users[0] and "provider_subject" not in users[0]
    assert len(repository.users) == 1 and len(repository.identities) == 1
    changed = client.patch("/api/v2/me", headers=auth(), json={"display_name": "家长"})
    assert changed.status_code == 200
    assert client.get("/api/v2/me", headers=auth()).json()["display_name"] == "家长"


@pytest.mark.parametrize(
    "body",
    [
        {"uid": "spoof"},
        {"openid": "spoof"},
        {"owner_user_id": str(uuid4()), "nickname": "x"},
        {"nickname": " "},
        {"nickname": "x" * 65},
        {"nickname": 42},
        {"nickname": "x", "raw_audio": "data"},
    ],
)
def test_child_creation_rejects_spoofing_and_invalid_contracts(client, body):
    response = client.post("/api/v2/children", headers=auth(), json=body)
    assert response.status_code == 422
    assert "spoof" not in response.text


def test_child_crud_archives_and_paginated_history(client):
    children = [create_child(client, nickname=str(index)) for index in range(3)]
    child = children[0]
    assert child["status"] == "active" and "owner_user_id" not in child
    response = client.get("/api/v2/children?limit=1&offset=1", headers=auth())
    assert response.json()["total"] == 3 and len(response.json()["items"]) == 1
    assert response.json()["limit"] == 1 and response.json()["offset"] == 1
    assert (
        client.patch(
            f"/api/v2/children/{child['id']}",
            headers=auth(),
            json={"nickname": "新昵称"},
        ).json()["nickname"]
        == "新昵称"
    )
    for _ in range(2):
        assert (
            client.delete(f"/api/v2/children/{child['id']}", headers=auth()).status_code
            == 204
        )
    assert (
        client.get(f"/api/v2/children/{child['id']}", headers=auth()).json()["status"]
        == "archived"
    )
    assert client.get("/api/v2/children", headers=auth()).json()["total"] == 2
    assert (
        client.get("/api/v2/children?include_archived=true", headers=auth()).json()[
            "total"
        ]
        == 3
    )
    assert (
        client.post(
            "/api/v2/sessions",
            headers=auth(),
            json={"child_profile_id": child["id"], "source_platform": "web"},
        ).status_code
        == 409
    )


def test_cross_user_idor_all_reads_and_writes(client):
    child = create_child(client)
    session = client.post(
        "/api/v2/sessions",
        headers=auth(),
        json={"child_profile_id": child["id"], "source_platform": "wechat"},
    ).json()
    requests = [
        ("GET", f"/api/v2/children/{child['id']}", None),
        ("PATCH", f"/api/v2/children/{child['id']}", {"nickname": "hijack"}),
        ("DELETE", f"/api/v2/children/{child['id']}", None),
        (
            "POST",
            "/api/v2/sessions",
            {"child_profile_id": child["id"], "source_platform": "web"},
        ),
        ("GET", f"/api/v2/sessions/{session['id']}", None),
        ("POST", f"/api/v2/sessions/{session['id']}/end", {}),
    ]
    requests += [
        ("GET", f"/api/v2/{kind}?child_profile_id={child['id']}", None)
        for kind in ["sessions", "emotions", "reports", "reports/current"]
    ]
    for method, path, body in requests:
        response = client.request(method, path, headers=auth("b"), json=body)
        assert response.status_code == 404, (method, path, response.text)
    for kind in ["children", "sessions", "emotions", "reports"]:
        assert client.get(f"/api/v2/{kind}", headers=auth("b")).json()["total"] == 0
    assert client.get("/api/v2/reports/current", headers=auth("b")).json() == {
        "status": "empty",
        "report": None,
    }
    client.delete(f"/api/v2/children/{child['id']}", headers=auth())
    assert (
        client.get(f"/api/v2/children/{child['id']}", headers=auth("b")).status_code
        == 404
    )


def test_session_metadata_is_server_created_and_end_is_idempotent(client):
    child = create_child(client)
    response = client.post(
        "/api/v2/sessions",
        headers=auth(),
        json={"child_profile_id": child["id"], "source_platform": "web"},
    )
    assert response.status_code == 201
    session = response.json()
    assert session["status"] == "active" and session["ended_at"] is None
    assert (
        datetime.fromisoformat(session["started_at"].replace("Z", "+00:00"))
        .utcoffset()
        .total_seconds()
        == 0
    )
    path = f"/api/v2/sessions/{session['id']}/end"
    first = client.post(path, headers=auth(), json={}).json()
    assert first["status"] == "ended" and first["ended_at"]
    assert client.post(path, headers=auth(), json={}).json() == first
    assert (
        client.post(path, headers=auth(), json={"ended_at": "2099-01-01"}).status_code
        == 422
    )


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=10001",
        "child_profile_id=invalid",
        "range_start=invalid",
        "range_start=2026-10-08T00:00:00Z&range_end=2026-10-07T00:00:00Z",
        "range_start=2026-10-07T00:00:00",
    ],
)
def test_bounded_ids_pagination_and_time_ranges(client, query):
    assert client.get(f"/api/v2/emotions?{query}", headers=auth()).status_code == 422


def test_readonly_derived_records_and_no_media_routes(client):
    for path in ["emotions", "reports", "media/upload", "video", "audio", "inference"]:
        response = client.post(f"/api/v2/{path}", headers=auth(), json={})
        assert response.status_code in {404, 405}
        assert "error" in response.json()
    assert client.get("/api/v2/reports/current", headers=auth()).json() == {
        "status": "empty",
        "report": None,
    }


def test_cors_exact_allowlist_and_non_reflection(client):
    response = client.options(
        "/api/v2/me",
        headers={
            "Origin": "https://client.example.test",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 204
    assert (
        response.headers["Access-Control-Allow-Origin"] == "https://client.example.test"
    )
    assert "access-control-allow-credentials" not in response.headers
    assert response.headers["Access-Control-Expose-Headers"] == "X-Request-ID"
    for origin in ["https://client.example.test.evil", "null", "https://evil.test"]:
        response = client.get("/api/v2/healthz", headers={"Origin": origin})
        assert response.status_code == 403
        assert "Access-Control-Allow-Origin" not in response.headers


def test_request_bounds_and_sanitized_errors(client):
    response = client.post("/api/v2/children", headers=auth(), content=b"x" * 16385)
    assert response.status_code == 413
    response = client.post(
        "/api/v2/children",
        headers={**auth(), "Content-Type": "application/json"},
        content='{"nickname":"sensitive-child", broken}',
    )
    assert response.status_code == 422 and "sensitive-child" not in response.text
    response = client.get("/api/v2/children/not-a-uuid", headers=auth())
    assert response.status_code == 422


def test_health_and_user_rate_limits_are_bounded():
    settings = Settings(health_rate_limit=2, private_rate_limit=2)
    with TestClient(
        create_app(settings, InMemoryRepository(), TestVerifier())
    ) as client:
        assert [client.get("/api/v2/healthz").status_code for _ in range(3)] == [
            200,
            200,
            429,
        ]
        assert [
            client.get("/api/v2/me", headers=auth()).status_code for _ in range(3)
        ] == [200, 200, 429]


def test_unconfigured_production_never_substitutes_fake_auth_or_memory():
    with TestClient(create_app(Settings())) as client:
        assert client.get("/api/v2/healthz").status_code == 200
        assert client.get("/api/v2/readyz").status_code == 503
        assert client.get("/api/v2/me", headers=auth()).status_code == 503


def test_imported_derived_records_are_owned_paginated_and_current_report_is_data_only(
    client, repository
):
    child = create_child(client)
    owner = client.get("/api/v2/me", headers=auth()).json()["id"]
    session = client.post(
        "/api/v2/sessions",
        headers=auth(),
        json={"child_profile_id": child["id"], "source_platform": "web"},
    ).json()
    timestamp = "2026-10-07T00:00:00.000000Z"
    emotion_id, report_id = str(uuid4()), str(uuid4())
    repository.records["emotions"][emotion_id] = {
        "id": emotion_id,
        "owner_user_id": owner,
        "child_profile_id": child["id"],
        "session_id": session["id"],
        "timestamp": timestamp,
        "category": "neutral",
        "confidence": 0.6,
        "valence": 0.0,
        "arousal": 0.2,
        "source": "test_fixture",
        "created_at": timestamp,
    }
    repository.records["reports"][report_id] = {
        "id": report_id,
        "owner_user_id": owner,
        "child_profile_id": child["id"],
        "range_start": timestamp,
        "range_end": timestamp,
        "summary": "Synthetic imported record; no clinical inference.",
        "created_at": timestamp,
    }
    for kind in ["emotions", "reports"]:
        response = client.get(
            f"/api/v2/{kind}?child_profile_id={child['id']}&range_start=2026-10-06T00:00:00Z&range_end=2026-10-08T00:00:00Z",
            headers=auth(),
        )
        assert response.status_code == 200
        assert (
            response.json()["total"] == 1
            and "owner_user_id" not in response.json()["items"][0]
        )
        assert client.get(f"/api/v2/{kind}", headers=auth("b")).json()["total"] == 0
        assert (
            client.get(
                f"/api/v2/{kind}?child_profile_id={child['id']}", headers=auth("b")
            ).status_code
            == 404
        )
    current = client.get(
        f"/api/v2/reports/current?child_profile_id={child['id']}", headers=auth()
    ).json()
    assert current["status"] == "available" and current["report"]["id"] == report_id
    assert client.get("/api/v2/reports/current", headers=auth("b")).json() == {
        "status": "empty",
        "report": None,
    }


def test_disabled_account_and_session_body_spoofing(client, repository):
    owner = client.get("/api/v2/me", headers=auth()).json()["id"]
    child = create_child(client)
    for extra in [
        {"owner_user_id": owner},
        {"uid": "spoof"},
        {"started_at": "2099-01-01T00:00:00Z"},
        {"raw_video": "data"},
    ]:
        response = client.post(
            "/api/v2/sessions",
            headers=auth(),
            json={"child_profile_id": child["id"], "source_platform": "web", **extra},
        )
        assert response.status_code == 422
    repository.users[owner]["status"] = "disabled"
    assert client.get("/api/v2/me", headers=auth()).status_code == 403


def test_unexpected_repository_failure_still_has_sanitized_error_and_metadata(
    client, repository, caplog
):
    async def fail(principal):
        raise RuntimeError("synthetic-token-private-child-sensitive")

    repository.resolve_user = fail
    with caplog.at_level("INFO", logger="soulcompanion.cloud.access"):
        response = client.get("/api/v2/me", headers=auth())
    assert response.status_code == 500
    UUID(response.headers["X-Request-ID"])
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert (
        "synthetic-token" not in response.text and "synthetic-token" not in caplog.text
    )
    assert "test-user-a" not in caplog.text
    assert "latency_ms" in caplog.text and '"route":"/api/v2/me"' in caplog.text


def test_repeated_concurrent_end_keeps_single_ended_timestamp(client):
    child = create_child(client)
    session = client.post(
        "/api/v2/sessions",
        headers=auth(),
        json={"child_profile_id": child["id"], "source_platform": "android_future"},
    ).json()
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _: client.post(
                    f"/api/v2/sessions/{session['id']}/end", headers=auth(), json={}
                ).json(),
                range(16),
            )
        )
    assert len({value["ended_at"] for value in results}) == 1


def test_chunked_body_limit_and_cors_preflight_rejects_unallowed_headers(client):
    response = client.post(
        "/api/v2/children", headers=auth(), content=iter([b"x" * 8000, b"y" * 9000])
    )
    assert response.status_code == 413
    response = client.options(
        "/api/v2/me",
        headers={
            "Origin": "https://client.example.test",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-wx-openid",
        },
    )
    assert response.status_code == 403


def test_request_deadline_is_fail_closed_without_gateway_timeout():
    class StalledVerifier(TestVerifier):
        async def verify(self, token):
            await asyncio.Event().wait()

    settings = Settings(upstream_timeout_seconds=0.02, request_timeout_seconds=0.03)
    with TestClient(
        create_app(settings, InMemoryRepository(), StalledVerifier())
    ) as client:
        response = client.get("/api/v2/me", headers=auth())
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "service_unavailable"
        assert response.headers["Cache-Control"] == "no-store"


def test_session_already_validated_active_may_complete_during_archive():
    async def scenario():
        pending, release = asyncio.Event(), asyncio.Event()

        class PausedSessionRepository(InMemoryRepository):
            async def create_owned(self, entity, record, owner):
                if entity == "sessions":
                    pending.set()
                    await release.wait()
                return await super().create_owned(entity, record, owner)

        service = ApplicationService(PausedSessionRepository())
        user = await service.resolve_user(
            AppPrincipal("policy-test", "test-environment")
        )
        child = await service.create_child(
            user, ChildWrite(nickname="Synthetic nickname")
        )
        body = SessionCreate(child_profile_id=child.id, source_platform="web")
        overlap = asyncio.create_task(service.create_session(user, body))
        await pending.wait()
        await service.archive_child(user, child.id)
        with pytest.raises(CloudError) as error:
            await service.create_session(user, body)
        assert error.value.status == 409
        release.set()
        assert (await overlap).status == "active"
        assert (await service.child(user, child.id)).status == "archived"

    asyncio.run(scenario())
