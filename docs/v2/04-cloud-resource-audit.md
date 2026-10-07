# Phase 04 preflight and CloudBase resource audit

Audit date: 2026-10-07, Asia/Shanghai. These observations came from the authenticated
CloudBase CLI 3.8.5 and read-only Tencent Cloud API calls, not from fake repositories.

## PHASE04_PREFLIGHT

```text
current_branch: 03-device-media-capture (before branch creation)
local_head: 2626fa387be793cbc27157f273494357b47ef8bc
phase03_remote_head: 2626fa387be793cbc27157f273494357b47ef8bc
modified: []
staged: []
untracked: []
phase03_clean: true
phase03_ci_status: success, 7/7 jobs
cloudbase_cli_available: true, 3.8.5
cloudbase_logged_in: true, current computer
cloudbase_environment_visible: true, owner-corrected environment below
ready_for_phase04: true, local implementation; deployment has separate gates
```

The exact Phase 03 [GitHub Actions run](https://github.com/C1801SYQ/SoulCompanion-AI/actions/runs/37138970428)
completed successfully. Fetch/prune, fast-forward pull, tracked/unstaged/staged
diffs and untracked-file inventory were checked before creating `04-cloud-backend`.
No reset, clean, restore, force push or master merge was used.

The supplied request originally named `soulcompanion-dev-d8d6p82fc7863a`.
Authenticated queries could not find that ID. The owner explicitly selected the
already-existing `soulcompanion-dev-d0dzo6f2a24211` in this conversation. All Phase 04
configuration and deployment must use that corrected ID. No environment was created.

## CLOUDBASE_RESOURCE_AUDIT

| Item | Observed value |
| --- | --- |
| Environment | `soulcompanion-dev-d0dzo6f2a24211` |
| Alias | `soulcompanion-dev` |
| Region | `ap-shanghai` |
| Status | `NORMAL` |
| Package | `baas_trial`, 体验版 |
| Expiration | `2027-04-07 23:59:59` |
| Overrun / automatic renewal | `false` / `false` |
| Document database | `tnt-28wj48qn2`, `RUNNING` |
| Existing document collections | 0, complete first page |
| MySQL | Not activated; environment-specific cluster query rejects missing cluster |
| Functions | 0, complete first page |
| HTTP service domains | 1 existing default domain, HTTPS enabled |
| Existing application gateway routes | 0, complete first page |
| Username authentication | Enabled |
| Email / anonymous / phone authentication | Disabled / disabled / disabled |
| WeChat AppID provided by owner | `wx11a055ed4dc69764`; binding and real client flow still need verification |

The existing public development domain is
`soulcompanion-dev-d0dzo6f2a24211-1501181209.ap-shanghai.app.tcloudbase.com`.
This is an observed gateway domain, not evidence of a deployed API endpoint.

## Included-resource usage snapshot

Billing cycle: 2026-10-07 through 2026-11-07. Included credits: 3000 resource
points. Reported consumption: 0.19 points; this is not a cash charge.
The snapshot recorded 19 secure gateway/API invocations and 3 Auth invocations;
SCF invocation, document read/write/storage, MySQL, cloud hosting, SMS and stored
media measurements were zero. Later read-only queries may appear in later usage.

No paid resource, upgrade, reserved concurrency, fixed egress IP, PostgreSQL,
GPU, additional environment or application storage was created by this audit.
The final delivery must repeat the cost query after real acceptance.

## Reproducible read-only checks

- `tcb env list --region ap-shanghai --json`: environment/package/overrun flags.
- `tcb env detail -e soulcompanion-dev-d0dzo6f2a24211 --json`: database and region.
- `tcb env usage -e soulcompanion-dev-d0dzo6f2a24211 --json`: included points and usage.
- `tcb fn list -e soulcompanion-dev-d0dzo6f2a24211 --json`: function inventory.
- `tcb env login get -e soulcompanion-dev-d0dzo6f2a24211 --json`: enabled login flags only.
- Official `tcb/2018-06-08` `ListTables`: the existing FlexDB database, limit 100,
  offset 0; returned `Tables: []`.
- Official `DescribeHTTPServiceRoute`: environment, limit 100, offset 0,
  `DomainType=HTTPSERVICE`; one domain with no configured routes.
- Official `DescribeMySQLClusterDetail`: environment-specific check; no cluster.

CLI complete configuration output is not persisted. Credential and user identity
values are never printed. Only explicit public fields, booleans, counters and
structural metadata are used in this report. The current CLI sometimes prepends
formatting text even with `--json`; safe parsing extracts the JSON block. A first
route query exited abnormally; subsequent identical read-only queries and the
underlying API query succeeded. `tcb db instance list` is account/region-wide,
so it is not used alone as proof of an environment's MySQL state.

## Deployment gates still open

Server-side document API authentication and WeChat's verified identity transport
must be established from current official APIs and tested. Public HTTP header
claims such as `x-wx-openid` are not sufficient authentication. No resources are
provisioned until local tests pass and each operation is confirmed to fit the
existing free package. Any price/upgrade/paid-resource confirmation stops deployment.

Official [package documentation](https://cloud.tencent.com/document/product/876/127357)
currently lists built-in MySQL support for the free trial; this audit does not
claim that MySQL inherently requires a paid upgrade.
