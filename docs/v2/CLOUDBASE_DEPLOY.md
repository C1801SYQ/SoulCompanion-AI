# Phase04 development deployment

Use only the owner-confirmed existing environment
`soulcompanion-dev-d0dzo6f2a24211`, Shanghai (`ap-shanghai`). This is a finite
`baas_trial` experience package, not an unlimited or permanent free plan.
Both overrun and auto-renew must remain disabled. Stop on any payment, upgrade,
resource collision or unknown confirmation. Never create a second environment.

## Reproducible local checks

Use Python 3.11 or later for the standalone API and Node 24 for the client.
Install `cloud/api/requirements-cloud.txt` and pytest for cloud tests. Existing
software regression dependencies remain in `requirements-web.txt` and
`requirements-dev.txt`.

```text
python -m pytest tests/cloud tests/cloud_tools -q
python scripts/cloud_schema.py
python scripts/cloud_package.py
python scripts/cloud_deploy.py
npm run client:typecheck
npm run client:test
npm run client:build:h5
npm run client:build:weapp
```

Schema and deployment commands default to planning. Package building downloads
only an exact pinned lightweight Linux CPython 3.11 wheel set; it never copies the
Windows virtual environment or the root inference dependencies. The ZIP contains
the independent API, its dependencies, and an LF bootstrap with executable mode
0755. The HTTP process listens on port 9000. Source-only packages created with
`--skip-dependencies` are test artifacts and cannot be deployed.

Deploy uses SCF's managed temporary COS upload because the packaged Linux
dependencies exceed the 1.5 MB inline `ZipFile` limit. This path obtains
`GetTempCosInfo` and uploads the function archive; it does not create an
application bucket, enable an additional storage product, or upload media.

The official CloudBase CLI 3.8.5 is installed locally under ignored
`.test-artifacts/cloudbase-cli`. Reproduce with the official npm package and
official browser login; do not copy another computer's login file. Deployment
helpers capture CLI output, inspect public fields, and withhold raw responses.

## Controlled apply

After local tests and independent review pass, inspect current trial resources:

```text
python scripts/cloud_admin.py
python scripts/cloud_schema.py --apply --create-server-key
python scripts/cloud_schema.py --apply
python scripts/cloud_deploy.py --apply
```

Key creation runs once and stores the key only in ignored
`.test-artifacts/cloudbase-phase04/.env`. Do not print this file or commit it.
The key is a server administrator key with a 30-day expiry. It is carried to the
HTTP function through temporary managed-environment configuration, outside the
uploaded code directory, then the temporary file is removed. Existing local key
files cause creation to stop; use a deliberate rotation procedure rather than
creating duplicate keys automatically.

`cloud/schema/001_metadata.json` defines seven project collections and thirteen
indexes, including the unique verified identity index. Provisioning is additive:
no collection or index is dropped. An owner/checksum marker at version 0 allows a
partial run to resume; version 1 is published only after collection ACLs and all
index definitions are verified. Foreign namespace collisions stop the command.

The function `sc-v2-api` uses Python3.11, 256 MB and a 3-second timeout, with no
prewarmed instance. Its ownership description is checked before any later update.
The gateway `/` route preserves `/api/v2` paths. The application verifies private
Bearer tokens; health remains public. Exact application CORS is independent from
authentication. Gateway quotas are 100 requests/second overall (the supported
gateway minimum) and 5 per client
IP; per-instance application quotas add another bounded layer. These counters are
development protections, not a distributed production rate limiter.

The existing system HTTP domain uses `CreateHTTPServiceRoute` with an owned
function and verified empty route list, matching the official declarative
deployer. The CLI `routes add` checks custom-domain binding through
`VerifyHTTPServiceRoute`, which rejects a system domain before route creation.
No custom domain, certificate, DNS record or paid gateway is created.

Configure `CLOUD_ALLOWED_ORIGINS` as exact origins. The initial acceptance origin
is `http://127.0.0.1:18404`; no public production site is authorized. Configure
`PUBLIC_API_BASE_URL` only for a local test or owner development build after the
deployed endpoint is verified. Public Cloudflare builds remain DEMO_ONLY.

## Real acceptance with existing fixtures

The environment already contains the two synthetic Phase04 Auth fixtures. Reuse
them rather than creating additional accounts. First build the local H5 with the
actual public API origin (without `/api/v2`):

```powershell
$env:PUBLIC_CLOUDBASE_ENV_ID = 'soulcompanion-dev-d0dzo6f2a24211'
$env:PUBLIC_CLOUDBASE_REGION = 'ap-shanghai'
$env:PUBLIC_WECHAT_APP_ID = 'wx11a055ed4dc69764'
$env:PUBLIC_API_BASE_URL = 'https://soulcompanion-dev-d0dzo6f2a24211-1501181209.ap-shanghai.app.tcloudbase.com'
$env:PUBLIC_DEMO_ONLY = 'false'
Remove-Item Env:CF_PAGES -ErrorAction SilentlyContinue
npm run client:build:h5
```

This changes only the current local terminal environment, not the public
Cloudflare deployment. Then run:

```text
python scripts/cloud_acceptance.py --browser --reuse-fixtures
python scripts/cloud_acceptance.py --apply --browser --reuse-fixtures
```

The first command is a plan with no cloud calls. The second requires exactly two
accounts whose names match the reserved `scphase04_` fixture pattern in a complete
environment user list. It resets only their generated in-memory passwords via
private stdin to the official CLI, then checks real API ownership, metadata and
SDK behavior. Other users are not modified. Passwords, private UIDs and tokens are
absent from OS command arguments, logs and public evidence. Active API tokens are
revoked on completion or attempted cleanup after a failure. Archived profiles and
ended sessions remain explicitly synthetic; acceptance does not delete records.

The browser server binds only `127.0.0.1:18404`, refuses an occupied
port, and stores no screenshots, HAR, trace or authentication state files.

## Evidence and limitations

Real deployment and API health must be tested separately from secret-free CI.
`deployment-public.json` contains public resource metadata only and explicitly
marks health acceptance pending. Reports must distinguish local fake repositories,
actual CloudBase HTTP/DB/auth acceptance, WeChat builds, DevTools and physical
devices. A package, route or marker alone is not a successful real CRUD test.

Official references: [trial resource limits](https://cloud.tencent.com/document/product/876/127357),
[FastAPI HTTP function](https://docs.cloudbase.net/cloud-function/frameworks-examples/fastapi),
[server API keys](https://cloud.tencent.com/document/product/876/129835),
[online token verification](https://docs.cloudbase.net/http-api/auth/auth-token-introspect),
[NoSQL HTTP specification](https://docs.cloudbase.net/openapi/nosql.v1.openapi.yaml),
[collection creation](https://cloud.tencent.com/document/api/876/127968),
[indexes](https://cloud.tencent.com/document/product/876/127964),
[administrator-only ACL](https://cloud.tencent.com/document/product/876/34819).
