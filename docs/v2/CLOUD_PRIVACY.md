# Phase04 cloud privacy boundary

The cloud API stores application users, verified identity mappings, child profile
nicknames and session metadata. Emotion records and reports are read-only in this
phase. An empty report stays empty; no clinical conclusion is invented.

The client never uploads camera frames, screenshots, PCM, audio chunks, device
IDs or device labels. Local camera/microphone processing remains in Phase03. The
cloud API rejects unknown JSON fields, raw media and client-provided owner IDs,
UIDs or OpenIDs. Cloud failure never holds a local microphone or camera open.

CloudBase owns password verification and token refresh. Web and WeChat adapters
share its official SDK token format; FastAPI verifies each access token through
the environment's online introspection endpoint. The private verified subject is
mapped to deterministic application UUIDs. The UI receives application records,
not identity mappings. Different CloudBase subjects are not silently linked.

Access/refresh tokens use an injected memory storage for both SDK initialization
and authentication. They are not placed in localStorage, sessionStorage,
IndexedDB, Taro storage, cookies, console logs or acceptance artifacts. Reloading
requires another login. Logout hides private UI before attempting provider
revocation; failed revocation is shown as unconfirmed. Account/profile changes
discard pending responses and clear prior private records.

All application collections use ADMINONLY permissions. Only the server's managed
environment has the CloudBase administrator API key. Frontend users cannot bypass
the application API with direct database queries. The key is environment-wide,
not a narrowly scoped collection key; protect it accordingly and rotate it before
its 30-day development expiration. Local credentials are confined to an ignored
`.env` file. Deployment config containing the key is temporary and removed even
on failures. CI has no real credentials and never deploys automatically.

Every private repository query includes the server-derived application owner.
Foreign and nonexistent IDs both return 404. UUID validity is checked; pagination,
time ranges and text lengths are bounded. Logs contain only request ID, route
template, status and latency. Response errors never echo input or upstream errors.

Archiving hides a profile from the default list and prevents subsequent session
starts. A session validated while its profile was active may complete during a
concurrent archive; archiving does not cancel existing or overlapping sessions.
Ending sessions remains possible and idempotent. No offline session queue is
persisted; failed metadata operations are shown explicitly.

The existing local SQLite database is not migrated or uploaded. The public
Cloudflare site remains DEMO_ONLY and does not initialize cloud authentication.
Synthetic acceptance accounts and records must be clearly separated from real
children's data. WeChat DevTools and physical-device results require their own
evidence; a successful build or mock adapter test is not device verification.
