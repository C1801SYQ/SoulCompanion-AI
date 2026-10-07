# Phase 04 database decision

Date: 2026-10-07. Target: the owner's existing
`soulcompanion-dev-d0dzo6f2a24211` environment in `ap-shanghai`.

| Candidate | Cost and actual availability | Selected |
| --- | --- | --- |
| CloudBase MySQL | Official trial table includes built-in MySQL, but this environment has no activated cluster. A verified free provisioning and secure FastAPI connection path has not been established. No instance is purchased or activated to discover pricing. | No |
| Existing CloudBase document database | Already running in this environment; 0 collections. Uses the included trial resources, with overrun disabled. Server authentication and collection rules must be verified before deployment. | Yes |
| Local in-memory repository | Isolated synthetic test data only; no cloud credentials or real user database. | Tests only |
| PostgreSQL / paid hosting / paid VPC | Outside the authorized zero-cost path. | No |

This is the request's permitted document-database fallback. The reason is the
availability of an already-running resource and the absence of a verified MySQL
provisioning path, rather than an assertion that MySQL is always paid.

The domain and application services depend on repository interfaces for users,
identities, child profiles, sessions, emotion records and reports. Routers do not
call a database SDK. The planned cloud implementation uses `CloudBaseDocumentRepository`; tests inject
an isolated in-memory implementation. Neither the cloud package nor CI reads the
existing local SQLite database or automatically migrates it.

Collections and indexes are versioned in `cloud/schema/`. Ownership is a required
query filter, including reads, updates, archives, pagination and session endings.
Identity creation must be safe under competing first requests. Raw audio, images,
device identifiers and device labels have no fields in the cloud schema.

A future MySQL migration can implement the same interfaces, provision a versioned
schema and indexes, explicitly export approved records, validate ownership and
counts, then change the repository configuration. It requires a separate cost and
connection audit. No migration or resource purchase occurs implicitly.
