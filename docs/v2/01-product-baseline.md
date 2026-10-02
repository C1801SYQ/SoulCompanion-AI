# Phase 01 — Verified product baseline

Date: 2026-10-02. Branch: `01-product-baseline`.

## Preservation

Parent commit: `09a9fe0cd455a810a04c48ac7226e4989266ee75`.

Preservation commit: `337731d559cef3359b54e741e51cb075d29eb661` —
`chore: preserve verified product delivery baseline`.

All 35 modified tracked files and 30 new source files from the previous delivery
were preserved. The only additional correction removed a trailing blank line in
the frontend test runner so that the staged whitespace check passed. No algorithms
or runtime behavior changed during this phase. No reset, clean, restore, overwrite,
or merge into master was performed.

The commit was pushed to `origin/01-product-baseline`; the remote branch was
verified with `git ls-remote --heads`. Git's configured credential manager worked
even though the separate GitHub CLI reported an invalid token.

## Tests

| Check | Result |
| --- | --- |
| Python 3.12 full pytest | 327 passed, 0 failures/errors |
| npm test | 38 DOM checks passed |
| npm run test:demo | 44 passed |
| npm run lint | Passed |
| npm run build | Passed, explicit DEMO-only static site |
| npm run test:e2e | 8 browser flows passed, zero fatal exceptions |
| git diff --cached --check | Passed |
| Submission safety audit | 65 UTF-8 text files, no secrets, real database, binary or generated dependency/test directories |

Tests used declared development dependencies and the fresh lightweight Web runtime.
Browser tests used actual FastAPI/SQLite with labelled synthetic fixtures, including
confirmed server shutdown and unseeded restart persistence. Evidence remains in
ignored `.test-artifacts/`; no private media or user data was committed. One
Starlette test-client deprecation warning remains.

## Known limitations and V2 transition

This preserved baseline is the previous local-only, single-user/single-child
product. It has no remote authentication, client media ingestion, multi-profile
ownership, WeChat build, or Android APK. The static site is a clearly labelled demo.
The optional Docker recipe and physical devices have not been executed or verified.
Remote Actions results must be checked independently of local tests.

V2 will obtain camera and microphone data from the active client device. Physical
actuators remain an optional future integration. The existing local boundary must
stay in place until authenticated `/api/v2` remote access is implemented.

The required branch chain is:

```text
01-product-baseline → 02-cross-platform-ui → 03-device-media-capture
→ 04-cloud-backend → 05-realtime-emotion-pipeline → 06-algorithm-modernization
→ 07-wechat-miniapp → 08-android-apk → 09-cloud-release → 10-release-candidate
```

Each phase inherits the preceding branch and passes its test/commit/push/remote
verification gate before the next branch is created. No automatic master merge.
