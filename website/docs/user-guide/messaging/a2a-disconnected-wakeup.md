# A2A disconnected replies and local Codex wakeup

The A2A adapter supports the standard `CreateTaskPushNotificationConfig`
(or inline `configuration.taskPushNotificationConfig`) extension. The sender
posts a v1.0 `StreamResponse` to the registered URL and, when configured,
protects it with `X-A2A-Signature: <hex HMAC-SHA256>` over the canonical JSON
(payload keys sorted, UTF-8, compact separators). The webhook must validate the
signature with a secret provisioned out of Git, validate `taskId`, `contextId`
and a terminal state, and reject replays or conflicting event IDs.

`plugins.platforms.a2a.wakeup.WakeupReceiver` is a **local extension**, not an
A2A method. It persists the validated push in SQLite before invoking its
callback. The callback is the explicit wakeup seam for the Codex turn. A
process cut after the commit is recovered with `recover()`; the event ID is a
primary key and therefore duplicate final sends do not invoke Codex twice.

The outbound A2A client still persists its local request and remote
`taskId`/`contextId` before sending bytes. After a stream cut it uses `GetTask`
(or the standard `SubscribeToTask` path where a live stream is desired); it
never automatically resends `SendStreamingMessage`. Native Hermes `send`
remains blocked. The local wakeup callback must not call native send.

## Authentication and validation checklist

1. Keep the HMAC secret in the runtime secret store, never in config, tests, or
   task payloads.
2. Verify the signature against the exact received JSON representation before
   parsing untrusted result fields into local state.
3. Validate the A2A response shape, task/context identity, and terminal state.
4. Bound request body, response text, and event IDs; reject malformed, non-final,
   stale, or conflicting events.
5. Persist first, then wake Codex. On callback failure leave the row pending and
   run `recover()` after restart.
6. Treat A2A push as a notification only: `GetTask` remains the source of truth.
