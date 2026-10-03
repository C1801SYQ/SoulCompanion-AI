# Phase 02 — Cross-platform client and design system

Date: 2026-10-03. Branch: `02-cross-platform-ui`.
Parent: `57c41fd7974a286c4901df01048c44a89f483777` on
`01-product-baseline`. No master merge or discarded baseline files.

## Product changes

`apps/client` contains a Taro 4.3 / React 18 / strict TypeScript client using
Taroify public components and shared SoulCompanion tokens. Home, Session,
Insights, Reports and Settings share desktop navigation and five mobile tabs.
The Emotion Orb has bounded valence/arousal/confidence mappings, text values,
slow breathing, OS reduced-motion support and an in-product off switch.

REAL uses a typed, validated adapter to the preserved V1 contracts. DEMO is
explicit, labelled synthetic data and performs no HTTP calls. Errors and offline
states never switch to DEMO. Each resource owns its cancellation, deadline,
retry/backoff and refresh cadence; stale source/range results are discarded.
Hidden pages stop polling and visible pages refresh. Preferences and observations
stay in memory. Markdown export requires a user action.

The previous client, SQLite service and local access restrictions remain intact.
Session shows camera/microphone off and requests no device permissions in this
phase. V1 records are emotion observations, not invented companionship sessions.
The report count is labelled accordingly; only V1 valence time series and mean
arousal are available. V2 session history and arousal series will require new
contracts. Existing V1 Markdown wording is retained by the adapter, including
legacy report content; new V2 reports must use the new non-clinical product terms.

## Design and current site evidence

The original Cloudflare site was opened in a real browser at 1440×900,
768×1024 and 390×844; screenshots and network evidence are retained in ignored
`.test-artifacts/v2-ui-baseline`. `UI_AUDIT.md` documents the older dashboard,
its unavailable API paths and mobile action placement. `DESIGN_SYSTEM.md` records
the chosen direction, tokens, initial design critique and reviewed sources.

Anthropic frontend-design, the requested Koubos ui-ux-pro-max fork and Taroify
README/license/skill text were read. No external skill or template setup script
was installed or executed. The new product source is shared across platforms;
browser-only export code is isolated in a platform module.

## Build tooling and dependency exceptions

Use Node.js 24 and lockfile installation with `--ignore-scripts`. The official
Taro React preset requires explicit `@babel/preset-react` and `react-refresh`
peers. The HTML template must retain Taro's entry injection marker; its absence
initially produced an empty HTML-only build, which was corrected before acceptance.
The build now emits actual JavaScript and CSS for all five pages.

The default older Vite toolchain had published advisories. Scoped overrides use
Vite 6.4.3 with Taro's Vite runner/framework and patched static-copy/esbuild/glob
dependencies. This is a tested compatibility override beyond Taro's advertised
Vite 4 peer range, not a claim of upstream certification. Vitest 4.1.11 and Babel
7.29.7 are pinned. The static-copy public export and actual Vite asset-copy build
were exercised on Node 24. Windows H5 production build and browser checks are the
current compatibility evidence; WeChat and Android remain separate phase gates.

The refreshed full npm audit retains **36 findings: 1 critical, 29 high,
6 moderate**. `npm audit --omit=dev` reports **16 high**; it is not clean.
Earlier 0/14 results became obsolete after updated upstream advisories.
The current findings occur in these paths:

- `download-git-repo`, `download`, `decompress`, `git-clone` and their dependencies:
  Taro remote-template scaffolding commands; not invoked to build this existing
  client. Do not run unreviewed remote initialization/templates.
- `latest-version`, `package-json` and older networking dependencies: Taro's
  explicit update command; not a production client or API dependency.
- `html-minifier`: Taro mini XML whitespace minification, explicitly disabled
  with `mini.minifyXML.collapseWhitespace=false`. An asynchronous replacement
  cannot be blindly substituted for the runner's synchronous API.
- `braces` through Chokidar, micromatch, fast-glob and workspace discovery:
  deeply nested build/watch glob input can exhaust the stack. Published latest
  `braces` 3.0.3 has no released fix. Build only reviewed source/configuration;
  never accept uploaded files or user patterns into this toolchain. Chokidar 4
  removes glob support and is not a compatible blind replacement.
- `http-cache-semantics` through the CLI networking chain: cross-user cached
  responses can be disclosed by max-stale handling. Latest 4.2.0 is affected and
  has no released fix. This application does not use the dependency to cache
  users' API responses. Its presence is retained and reported, not described as
  patched.

Raw audit JSON is retained under ignored `.test-artifacts/phase02-npm-*.json`.
There is no claim that the full development dependency graph has a clean audit.
Lifecycle scripts are disabled, and no third-party scaffolding code was executed.
Actual Taro H5 runtime entrypoints and generated bundles were inspected; no
imports/calls of these glob/cache tool dependencies were found in the client.
This supports a reachability limitation, not a claim that the vulnerable packages
are fixed. Npm labels build/helper peers as production dependencies too.

CI records the complete non-clean audit. A separate, explicit exception policy
accepts only the 10 reviewed advisory IDs and their current named package paths,
bound to the reviewed lockfile fingerprint. New advisories, changed dependency
paths, unavailable audits or changed locks fail the policy check. It prints and
uploads retained finding counts; it does not turn npm's non-zero result into a
claim of zero vulnerabilities. Re-review exceptions when dependencies, build
inputs or deployment behavior change. The policy's rejection paths have unit
checks. This keeps known unresolved tool risks visible without an unrestricted
`continue-on-error` for future audit results.
Primary advisories used in patch review include
[Vite](https://github.com/advisories/GHSA-fx2h-pf6j-xcff),
[Swiper](https://github.com/advisories/GHSA-hmx5-qpq5-p643),
[Vitest](https://github.com/advisories/GHSA-82fw-gwwq-j7x9),
[static-copy](https://github.com/advisories/GHSA-pp7p-q8fx-2968), and
[esbuild](https://github.com/advisories/GHSA-67mh-4wv8-2f99). Unfixed advisories:
[braces](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) and
[http-cache-semantics](https://github.com/advisories/GHSA-ch52-4w7c-c8xp).

## Validation

| Check | Actual result |
| --- | --- |
| Fresh offline lockfile install, lifecycle scripts disabled | Passed on Node 24 |
| Client strict TypeScript | Passed |
| Client unit checks | 61 passed in 5 files |
| H5 production, real-capable and separately compiled DEMO_ONLY | Both built actual five-page JS/CSS |
| REAL browser acceptance | 14 checks passed, actual FastAPI/V1 + 65-record synthetic SQLite |
| DEMO_ONLY browser acceptance | 3 grouped checks passed; 0 API/media requests, REAL disabled |
| Responsive layouts | 5 pages × 375/390/430/768/1024/1440 px, in each build |
| Keyboard and motion | Main buttons, export, navigation and switch work; OS reduction/product off disable motion |
| Actual action text | Visible, enabled attribute absent; contrast 7.538, minimum required 4.5 |
| Hidden/show lifecycle | Simulated visibilitychange stops polling for 3.2 s and resumes a real request |
| Render fault recovery | Deliberate Date formatter fault shows generic fallback, stops polling, keyboard retry restores REAL |
| Preserved Python suite | 327 passed; one known Starlette deprecation warning |
| Preserved frontend / demo | 38 / 44 checks passed |
| Preserved browser flows | 8 passed |
| Ruff, compileall, npm lint, legacy static build | Passed |
| Advisory exception policy | 11 tests passed; current 36 findings remain visible; failure replaces stale evidence |

The original REAL/browser evidence is retained in
`.test-artifacts/v2-client-acceptance/run-5oH9mX`; compiled demo-only evidence is
in `run-sF5pwS`. Every fixture process exited normally and its owned TCP port
returned ECONNREFUSED before success was written. REAL had zero unexpected
uncaught exceptions; its two console errors were from deliberately stopped
network/render-fault scenarios. DEMO_ONLY had zero console errors. No camera or
microphone permission was requested. The visibility test is an explicit simulated
lifecycle stimulus, not a physical OS background/lock-screen test. Basic DOM and
text-contrast checks do not establish full screen-reader/WCAG conformance.

The CI retains all baseline jobs and adds an independent H5 type/unit/build/browser
job, full audit evidence and the scoped advisory policy. Local success does not
establish a remote Actions result. Commit/push verification precedes creation of
`03-device-media-capture`.

No real device capture, cloud login, deployment, approved WeChat domain or APK has
been validated in this phase. The user has no cloud hosting account or WeChat
AppID yet; subsequent source/build work can proceed, while real publication and
device verification require those registrations.
