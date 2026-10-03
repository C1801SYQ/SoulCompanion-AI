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
npm run client:test:media
```

The browser checks also require declared Web Python dependencies and Playwright
Chromium. Set `SOULCOMPANION_PYTHON` to a Python interpreter with
`requirements-web.txt` installed if `python` is not that interpreter. The runner
creates an isolated, labelled synthetic database and closes its own servers.
Evidence is written to ignored `.test-artifacts/v2-client-acceptance/`.
The media runner uses Chromium's virtual devices, never the developer's physical
camera or microphone. Its separate evidence is in `.test-artifacts/v2-media-acceptance/`.

For development, run `npm --prefix apps/client run dev:h5`. The development server
binds to loopback. REAL is the default and requires a same-origin backend; there
is no production proxy or bypass of the preserved V1 local access boundary.
Changing to DEMO in Settings uses explicit synthetic data and makes no API
requests. Failed REAL requests remain errors or offline states.

## Public build configuration

- `PUBLIC_API_URL`: API origin, or an explicit `/api/v1` base. Empty means
  same-origin. It is public build configuration, never a credential.
- `PUBLIC_DEMO_ONLY=true`: build explicitly synthetic emotion data with REAL disabled.
  Local camera/microphone preview still works after an explicit Start action.
  This flag does not turn a local device into a fake device or an inference source.
- Phase03 builds on Cloudflare Pages (`CF_PAGES=1`) always use synthetic emotion data,
  even if a dashboard environment variable is missing or set to false. Local builds
  without this Pages marker still support REAL. The Preview CI job exercises this
  rule with `CF_PAGES=1` and `PUBLIC_DEMO_ONLY=false`; device Start remains available.

Do not put passwords, tokens, signing keys, real records or media in these values
or the repository. Preferences and client observations stay in memory. An
explicit Markdown export is user initiated. Web capture does not create files.
WeChat's recording/encoding APIs can create owned temporary files, which the
adapter deletes after use; cleanup failure is reported instead of hidden.

## Scope

Phase03 adds explicit local camera/microphone sessions, bounded JPEG/WebP frames,
short audio events, microphone input intensity and lifecycle cleanup. Page load
does not request permissions. Start works without an emotion backend, including
DEMO_ONLY; audio/video is not uploaded, stored in browser storage or used to
invent an emotion, transcript or AI response. Stop, navigation and background
release devices, and returning to the page does not restart capture.

The WeChat adapter is checked for TypeScript/platform boundaries in this phase;
DevTools and physical devices require Phase07 verification. Android reuses the
Web adapter; this phase adds no APK, Capacitor dependency or native bridge.
Animation supports the OS reduced-motion preference and in-product switch.
See `docs/v2/MEDIA_PRIVACY.md` and the Phase03 report for verified evidence and
the distinction between virtual-browser, Fake and physical-device tests.

Cloudflare Preview configuration remains root `apps/client`, command
`npm ci --ignore-scripts && npm run build:h5`, output `dist`, Node.js 24 and
`PUBLIC_DEMO_ONLY=true`. Pushing Phase03 must not change the production branch.

Design direction and the original site audit are in `docs/v2/`. Dependencies are
locked; install lifecycle scripts are disabled. Security exceptions in unused
Taro scaffolding tools must be tracked in the phase report. Do not run remote
template initialization commands as part of building this existing client.
