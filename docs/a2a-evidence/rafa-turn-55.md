# Rafa TURN 55 — real GatewayRunner session-path canary

## Scope

This change keeps the canary foreground, loopback-only and isolated. It uses temporary HOME, sessions directory, SQLite TaskStore, random HTTP port and test-only bearer. No production model configuration, listener, gateway, Compose or native send is used.

The canary now reuses `GatewayRunner._handle_message_with_agent` unchanged. Only the `_run_agent` model seam is replaced with an explicitly simulated provider result. Consequently admission/wiring, session resolution and preparation, task dispatch, response delivery, persistence, SSE parsing, adapter close/reopen and GetTask-only recovery remain exercised by the real gateway/adapter path.

## Result

Command:

    .venv/bin/python scripts/run_gateway_http_stub_canary.py --output /tmp/turn55-canary-result.json

Observed result (sanitized):

    send_state=TASK_STATE_COMPLETED
    get_state=TASK_STATE_COMPLETED
    reply=TURN55_SIMULATED_MODEL_REPLY
    get_reply=TURN55_SIMULATED_MODEL_REPLY
    model_calls=1
    first_listener_closed=true
    second_listener_closed=true

`GetTask` after adapter close/reopen returned the same persisted artifact and did not invoke the simulated model again. Both temporary listeners were checked after disconnect and rejected loopback connections. `git diff --check` passed.

The run emitted pre-existing local warnings about the temporary profile's state journal mode and project-webui-sync reconciliation; these did not affect the canary (exit code 0) and are not part of this change.

## Limits

This is an isolated fixture canary, not Codex-to-Hermes E2E, a real model invocation, ObjectiveGrant/broker enforcement, human approval, protected native `send`, exactly-once external effects, or production readiness. The fixture bearer is test-only and never written to the JSON result. No public endpoint or production configuration was changed.
