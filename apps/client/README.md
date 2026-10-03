# SoulCompanion V2 client

Shared Taro 4 / React / TypeScript client. Phase 02 provides Home, Session,
Insights, Reports and Settings, with desktop navigation and mobile bottom tabs.
The previous Web client remains in `web/static/`.

## Run and verify

Use Node.js 24 and Python 3.12. From the repository root:

```sh
npm ci --ignore-scripts
npm --prefix apps/client ci --ignore-scripts
npm run client:typecheck
npm run client:test
npm run client:audit
npm run client:build:h5
npm run client:test:e2e
```

The browser checks also require declared Web Python dependencies and Playwright
Chromium. Set `SOULCOMPANION_PYTHON` to a Python interpreter with
`requirements-web.txt` installed if `python` is not that interpreter. The runner
creates an isolated, labelled synthetic database and closes its own servers.
Evidence is written to ignored `.test-artifacts/v2-client-acceptance/`.

For development, run `npm --prefix apps/client run dev:h5`. The development server
binds to loopback. REAL is the default and requires a same-origin backend; there
is no production proxy or bypass of the preserved V1 local access boundary.
Changing to DEMO in Settings uses explicit synthetic data and makes no API
requests. Failed REAL requests remain errors or offline states.

## Public build configuration

- `PUBLIC_API_URL`: API origin, or an explicit `/api/v1` base. Empty means
  same-origin. It is public build configuration, never a credential.
- `PUBLIC_DEMO_ONLY=true`: build an explicitly labelled demo with REAL disabled.

Do not put passwords, tokens, signing keys, real records or media in these values
or the repository. Preferences and client observations stay in memory. An
explicit Markdown export is the only client file creation in this phase.

## Scope

Session currently shows media off and requests no camera/microphone permissions.
Client capture, authenticated V2 services, WeChat and Android packaging follow
their numbered branches. A successful H5 build alone does not validate those
targets. Animation supports both the OS reduced-motion preference and the
in-product switch, with text equivalents for all Orb values.

Design direction and the original site audit are in `docs/v2/`. Dependencies are
locked; install lifecycle scripts are disabled. Security exceptions in unused
Taro scaffolding tools must be tracked in the phase report. Do not run remote
template initialization commands as part of building this existing client.
