# Phase 04 cloud architecture

Status: implementation in progress; this document is not a deployment claim.

The verified parent is Phase 03 commit
`2626fa387be793cbc27157f273494357b47ef8bc`. Phase 04 adds a separate lightweight
FastAPI application under `cloud/api/`, with versioned `/api/v2` routes.
Existing local `/api/v1`, local SQLite and the local-only security boundary remain
independent. The cloud entrypoint does not import the local emotion/hardware runtime.

```text
Web official Auth SDK / WeChat platform adapter
  -> verified CloudBase identity
  -> HTTPS /api/v2
  -> FastAPI contracts + application service
  -> owner-required repository interfaces
  -> existing CloudBase document database
```

The target is `soulcompanion-dev-d0dzo6f2a24211`, `ap-shanghai`; the public WeChat
AppID is `wx11a055ed4dc69764`. These identifiers are public configuration.
Credentials are kept exclusively in managed secret/environment storage or an
ignored local `.env`; they are never recorded in reports, logs or acceptance artifacts.

## API contract

IDs are UUID strings and times are server-produced UTC ISO strings. Lists use
`{items, limit, offset, total}`. Pydantic models forbid unknown request fields.
Other users' IDs and unknown IDs consistently return 404.

- Public process health and dependency readiness: `/api/v2/healthz`, `/api/v2/readyz`.
- User: `GET/PATCH /api/v2/me`.
- Profiles: list/create at `/api/v2/children`; get/update/archive by child ID.
- Session metadata: list/create at `/api/v2/sessions`; get and idempotent end by ID.
- Read-only emotion history and reports, including `/api/v2/reports/current`.
- No media, audio, video, inference or raw-data import endpoints.

Authentication resolves an application user from a verified principal. Request
JSON never chooses `owner_user_id`, UID or OpenID. Every repository operation
requires the resolved owner and queries with that owner. CloudBase remains the
identity source; the application does not store passwords or sign its own JWTs.

## Platform boundaries

The Web adapter uses the official CloudBase SDK with explicit in-memory token
storage. Server verification uses the documented token introspection service;
an HTTP 200 empty object is rejected, and identity-service failures fail closed.
Unverified decoded JWT claims and public WeChat header claims are not accepted.
The WeChat adapter must use a documented, verified platform transport to the
same application layer. Its actual end-to-end evidence remains pending.

Cloud account/profile state is independent of the V1 `AppProvider` and polling
loop. Logout, account changes and profile changes invalidate private data and
pending responses. Public Cloudflare DEMO builds do not initialize cloud Auth or
make cloud requests. A local real-capable build requires an explicitly configured
API endpoint produced by deployment.

Local camera/microphone Start and End remain controlled by Phase 03. An
authenticated user with a selected profile may create cloud session metadata;
cloud failure cannot prevent local Stop. Lifecycle stops and late session-create
responses must be handled without associating old metadata with a new account.
Frames, PCM/WAV bytes, device IDs and labels never enter cloud transports.

## Deployment and evidence

The minimal HTTP Function package uses the official supported Python runtime,
port 9000, an LF bootstrap and Linux-compatible pinned dependencies. It contains
no models, GPU/robot/audio frameworks or existing local database. Document API
server credentials must be explicitly configured; HTTP Functions cannot assume
ordinary event functions' default administrator credentials.

CI uses injected fake Auth/repositories/gateways. Real authenticated acceptance
is separate, uses explicit synthetic data and never stores credentials. Schema
provisioning is versioned and additive. Deployment is restricted to the existing
trial environment, with exact CORS origins, bounded requests, rate limits and
sanitized request-ID logs. The final report separates fake/local checks, real
cloud checks, DevTools manual checks and physical-device checks.
