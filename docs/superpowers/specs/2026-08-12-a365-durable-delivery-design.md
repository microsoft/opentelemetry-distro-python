# Agent365 Durable Delivery Design

## Decision

Add durable store-and-forward delivery to the Python Agent365 exporter using only
the Python standard library. Persistence is enabled by default and can be
disabled explicitly. The implementation uses SQLite rather than file-per-record
blobs because SQLite provides atomic claims, deletion, retention, and capacity
accounting without an additional dependency.

The existing OpenTelemetry `BatchSpanProcessor` remains responsible for queueing,
force flush, and shutdown. Python does not need the custom processor state machine
introduced by the .NET change.

## Alternatives considered

1. **SQLite durable queue (selected).** Atomic transactions make replay leases and
   concurrent exporter access reliable. The trade-off is a small amount of schema
   and migration code.
2. **One JSON file per payload.** This is easy to inspect but requires custom
   atomic-rename, leasing, cleanup, capacity, and corruption handling.
3. **Memory-only retry queue.** This avoids sensitive disk persistence but loses
   telemetry on process exit and does not solve the failure mode addressed by the
   .NET feature.

## Public configuration

Extend `Agent365ExporterOptions` and the distro configuration surface with:

- `disable_offline_storage: bool = False`
- `storage_directory: str | None = None`

When no directory is supplied, use a private application-specific directory:

- Windows: `%LOCALAPPDATA%\Microsoft\Agent365\OpenTelemetry\<identity-hash>`
- Other platforms: `$XDG_STATE_HOME/microsoft/agent365/opentelemetry/<identity-hash>`
  or `~/.local/state/microsoft/agent365/opentelemetry/<identity-hash>`
- If no home/state directory is usable, fall back to
  `tempfile.gettempdir()/microsoft-agent365-opentelemetry/<identity-hash>`

On POSIX, directories are forced to mode `0700` and the database to `0600`.
Existing paths that are not owned by the current user are rejected.

## Components

### Delivery result

Replace the HTTP helper's boolean result internally with a disposition containing:

- delivered
- retryable failure, including an optional retry-after delay
- permanent failure

HTTP 401, 408, 429, 5xx, transport errors, and timeouts are retryable. HTTP 403
and other 4xx responses are permanent. A token resolver exception is retryable;
an empty token is permanent.

### Per-identity transmission gate

Maintain gate state per `(tenant_id, agent_id, agentic_user_id, endpoint mode)` so
one throttled identity cannot block healthy identities.

Each gate has:

- closed: sends proceed
- backoff: payloads are persisted without attempting the network
- half-open: one probe may proceed

`Retry-After` is honored when present. Otherwise use full-jitter exponential
backoff with a 10-second floor and one-hour cap. `time.monotonic()` drives
in-process deadlines.

### SQLite durable queue

Persist the complete serialized request plus identity and endpoint metadata.
Records include a schema version, creation time, lease deadline, and retry count.

The queue:

- is capped at 50 MB
- retains records for two days
- atomically leases records before replay
- deletes permanent/invalid records
- retains retryable and token-resolution failures
- tolerates duplicate delivery if deletion fails

Storage initialization or write failures are logged and cause the affected export
to return failure; they are never represented as successful persistence.

### Replay coordinator

A single daemon thread starts lazily after the first exporter use. It wakes on
new persisted work and periodically:

1. Claims up to ten records.
2. Resolves a fresh token for each identity.
3. Checks the identity gate.
4. Sends the stored payload.
5. Deletes delivered or permanent records.
6. Releases retryable records and updates gate backoff.

Shutdown signals the thread, waits within the caller's timeout where available,
then closes storage and the HTTP session exactly once. The resolver call cannot
be forcibly cancelled because the public resolver API is synchronous; this is
documented and the replay thread is daemonized so it cannot prevent interpreter
exit.

## Export semantics

`SpanExportResult.SUCCESS` means each generated chunk was delivered or durably
stored. `FAILURE` means at least one chunk was dropped, could not be stored, had
an invalid/empty token, or received a permanent response.

The exporter no longer sleeps through long server backoff windows. Retryable
failures are persisted and replayed instead, reducing pressure on the
`BatchSpanProcessor` worker.

## Testing

Tests cover:

- HTTP status and exception classification, including 401 and `Retry-After`
- per-identity gate isolation and single half-open probes
- SQLite round trips, leases, retention, capacity, corruption, and permissions
- export success when persistence succeeds and failure when it does not
- replay with a fresh token after restart
- permanent failures deleting stored records
- idempotent shutdown and replay-thread termination
- option propagation through both distro and helper construction paths

