# Agent365 Durable Delivery Hardening Design

## Decision

Harden the Python durable-delivery implementation to match the behavioral
guarantees in `microsoft/opentelemetry-distro-dotnet#137`. Keep SQLite as the
Python persistence mechanism, but treat the merged .NET tests as the contract
for retry timing, endpoint reconstruction, poison-record handling, producer
capacity, replay lifecycle, and deterministic shutdown.

## Alternatives considered

1. **Parity-first hardening (selected).** Port each observable .NET guarantee
   while retaining Python-appropriate storage and synchronization primitives.
   This minimizes cross-language behavior drift without copying implementation
   details that do not fit Python.
2. **Patch only the known review findings.** Smaller initially, but leaves
   behavior dependent on incidental implementation details and risks missing
   related .NET tests.
3. **Replace the exporter and storage architecture wholesale.** Could mirror
   .NET structure more literally, but creates unnecessary migration and
   compatibility risk.

## Durable record contract

Durable records store identity and payload, not a complete destination URL.
The supported schema version and all required fields are validated when records
are claimed. Unsupported, incomplete, or malformed records are poison records:
they are deleted and replay continues with later records.

Replay reconstructs the endpoint from the persisted identity and current
exporter configuration. It never sends a bearer token to a plaintext endpoint.
If the reconstructed endpoint is not HTTPS, the record is retained, the replay
pass stops, and an actionable diagnostic is emitted.

## Transmission gate and retry timing

Healthy closed-state traffic remains concurrent. Exclusive ownership applies
only when a backoff period expires and one half-open probe is selected.

`Retry-After` accepts both delta-seconds and HTTP-date syntax. Positive delays
are honored exactly up to the one-hour cap. Invalid, zero, or negative values
fall back to full-jitter exponential backoff. Backoff exponent growth remains
saturated to avoid overflow.

## Live export behavior

Permanent failure stops subsequent chunks for the same identity but does not
prevent unrelated identities from exporting. Retryable failures enter backoff
and are successful only when the payload is durably stored.

Batch configuration is validated before component-construction error handling.
Invalid queue size, schedule delay, or batch size raises a configuration error
instead of silently omitting the Agent365 exporter.

## Batch processor lifecycle

Introduce an Agent365-owned batch processor rather than relying on the standard
SDK processor's shutdown and capacity behavior. The processor uses atomic
capacity reservation so concurrent producers cannot silently evict accepted
spans. Shutdown stops new acceptance, drains every accepted span, waits for an
active export before exporter shutdown, and performs exporter shutdown exactly
once.

A caller timeout may stop waiting, but it must not make active worker cleanup
unsafe. The worker retains ownership of final exporter shutdown and disposal.
Force flush uses the same completion accounting and never races exporter
cleanup.

## Replay and resource lifecycle

Replay deletion results are checked. A failed deletion after successful delivery
logs duplicate-delivery risk and is not counted as removed. Retryable records
are released and stop the current pass; permanent and poison records are deleted
without blocking unrelated records.

Exporter shutdown signals replay and waits for it to finish before closing
storage or the HTTP session. If a bounded caller wait expires, cleanup ownership
stays with the replay/export worker; resources are not closed underneath active
work. Concurrent shutdown calls are idempotent.

## Testing

Add regression tests corresponding to the hardened .NET cases:

- closed-state concurrency and one half-open probe
- delta and date `Retry-After`, positive exact delays, and invalid fallback
- unsupported/incomplete/corrupt record deletion without queue blockage
- endpoint reconstruction and plaintext replay refusal
- deletion-failure duplicate-risk diagnostics
- permanent first-chunk isolation by identity
- atomic producer capacity under concurrency
- shutdown draining, active-export ordering, timeout ownership, and idempotence
- invalid batch configuration raising at the public API

Existing durable-delivery, restart, exporter, distro, formatting, lint, typing,
and full test suites remain required before the branch is pushed.
