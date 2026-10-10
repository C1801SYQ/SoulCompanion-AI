"""Observed CloudBase OAuth rejections are distinct from provider availability.

Every provider interaction is a deterministic MockTransport. No real tokens,
accounts, deployments, or CloudBase requests are used.
"""

import asyncio

import httpx
import pytest

from cloud.api.soulcompanion_cloud.auth import CloudBaseTokenVerifier
from cloud.api.soulcompanion_cloud.config import Settings
from cloud.api.soulcompanion_cloud.errors import CloudError


CONFIG = Settings(env_id="synthetic-auth-env")
PRIVATE_DETAIL = "synthetic-private-provider-description"


def rejected(status: int, body: object, expected: int) -> None:
    async def scenario():
        calls = []

        def transport(request):
            calls.append(request)
            assert request.method == "GET"
            assert (
                str(request.url)
                == "https://synthetic-auth-env.api.tcloudbasegateway.com/auth/v1/token/introspect"
            )
            assert (
                request.headers["authorization"] == "Bearer synthetic-untrusted-token"
            )
            return httpx.Response(status, json=body)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        ) as client:
            with pytest.raises(CloudError) as error:
                await CloudBaseTokenVerifier(CONFIG, client).verify(
                    "synthetic-untrusted-token"
                )
            assert error.value.status == expected
            assert error.value.code == (
                "unauthorized" if expected == 401 else "service_unavailable"
            )
            assert PRIVATE_DETAIL not in str(error.value)
            assert "synthetic-untrusted-token" not in str(error.value)
            assert len(calls) == 1

    asyncio.run(scenario())


def test_observed_malformed_token_400_failed_precondition_int9_is_unauthorized():
    # Live introspection rejected a public synthetic malformed token with HTTP 400,
    # STRING error "failed_precondition" and integer error_code 9. The official
    # CloudBase JS SDK 3.10.1 OAuth enums corroborate this string/code pair. The
    # provider description is intentionally replaced; it must not affect behavior.
    rejected(
        400,
        {
            "error": "failed_precondition",
            "error_code": 9,
            "error_description": PRIVATE_DETAIL,
        },
        401,
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"error": "failed_precondition"},
        {"error": "failed_precondition", "error_code": "9"},
        {"error": "failed_precondition", "error_code": True},
        {"error": "failed_precondition", "error_code": 9.0},
        {"error": "failed_precondition", "error_code": 14},
        {"error": "unavailable", "error_code": 9},
        {"error": "unauthenticated", "error_code": 16},
        {"error": {"code": "failed_precondition"}, "error_code": 9},
        {"error": "FAILED_PRECONDITION", "error_code": 9},
        {"error": " failed_precondition ", "error_code": 9},
        [],
        None,
        "failed_precondition",
    ],
)
def test_unknown_or_unexpected_400_stays_provider_unavailable(body):
    rejected(400, body, 503)


@pytest.mark.parametrize("status", [302, 408, 429, 500, 502, 503, 504])
def test_observed_error_family_on_other_statuses_never_hides_provider_failure(status):
    rejected(
        status,
        {
            "error": "failed_precondition",
            "error_code": 9,
            "error_description": PRIVATE_DETAIL,
        },
        503,
    )


@pytest.mark.parametrize("status", [401, 403])
def test_existing_explicit_provider_auth_denial_remains_unauthorized(status):
    rejected(
        status, {"error": "unauthenticated", "error_description": PRIVATE_DETAIL}, 401
    )


@pytest.mark.parametrize("status", [200, 400, 500])
def test_malformed_provider_json_stays_unavailable_without_leaking_description(status):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(status, text=PRIVATE_DETAIL)
            )
        ) as client:
            with pytest.raises(CloudError) as error:
                await CloudBaseTokenVerifier(CONFIG, client).verify(
                    "synthetic-untrusted-token"
                )
            assert error.value.status == 503 and PRIVATE_DETAIL not in str(error.value)

    asyncio.run(scenario())


def test_success_still_requires_online_provider_verified_subject_and_environment():
    async def scenario():
        calls = []

        def transport(request):
            calls.append(request)
            return httpx.Response(
                200,
                json={
                    "sub": "synthetic-verified-subject",
                    "client_id": CONFIG.env_id,
                    "token_type": "Bearer",
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        ) as client:
            principal = await CloudBaseTokenVerifier(CONFIG, client).verify(
                "synthetic-untrusted-token"
            )
        assert (
            principal.subject == "synthetic-verified-subject"
            and principal.issuer == CONFIG.env_id
        )
        assert principal.provider == "cloudbase_auth"
        assert len(calls) == 1 and "synthetic-verified-subject" not in repr(principal)

    asyncio.run(scenario())


def test_timeout_stays_unavailable_and_does_not_accept_token_claims():
    async def scenario():
        def transport(request):
            raise httpx.ReadTimeout(PRIVATE_DETAIL, request=request)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        ) as client:
            with pytest.raises(CloudError) as error:
                await CloudBaseTokenVerifier(CONFIG, client).verify(
                    "synthetic-untrusted-token"
                )
            assert error.value.status == 503 and PRIVATE_DETAIL not in str(error.value)

    asyncio.run(scenario())
