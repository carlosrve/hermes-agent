# A2A transport baseline and objective-contract handoff

## Current authority

The shared contract at https://git.vauxoo.com/carlosrve/a2a/-/blob/coordination/a2a-integration/docs/contract/objectives-v1.md supersedes historical per-dispatch approval proposals in local research documents. Authorization is reusable for an objective; exceptions return through the root coordinator to the originating client. Mandatory runtime safeguards remain in force.

This baseline implements streaming outbound transport with early durable task/context correlation, uncertain delivery, GetTask-only recovery, and opt-in native prepare/show/resume. Native send remains blocked. It does not implement ObjectiveGrant, authenticated human receipts, results usable by the coordinator, or bidirectional E2E acceptance.

## Verification of preserved implementation

Base: 1c8aaad2180bbf2fc34f097ab90d069170584ccd. Existing source changes preserved without behavioral edits during onboarding. Native/outbound SHA256 respectively:

- 6625dc11fe39a715a7d4a4d7c8f841b18bbe245efcd76c4a4559126384443b84
- 6efca80535214c90769af2828ef411f0fef6fe0b58ae7545bafc1997601376f0

Onboarding reran the canonical runner using an isolated Python 3.12 virtualenv with dev extras because the old .venv interpreter was unavailable. Result: **22 files, 774 passed, 0 failed**, retries disabled. These correspond to the historical 690 canonical + 77 discovery + 7 executor regressions; no new test count or E2E claim.

Command: `HERMES_PYTHON=/workspace/inbox/a2a-test-venv/bin/python scripts/run_tests.sh tests/plugins/test_a2a_outbound_recovery.py tests/plugins/test_a2a_outbound_validation.py tests/plugins/test_a2a_plugin.py tests/plugins/test_a2a_phase23.py tests/plugins/test_a2a_schema_registration.py tests/plugins/test_a2a_tools_gate.py tests/tools/test_a2a_reason_roundtrip.py tests/tools/test_approval.py tests/tools/test_approval_interrupt.py tests/tools/test_approval_config_readonly.py tests/gateway/test_approvals_command.py tests/plugins/test_a2a_native_tools.py tests/plugins/test_a2a_native_dispatch.py tests/test_model_tools.py tests/test_model_tools_async_bridge.py tests/tools/test_tool_search.py tests/tools/test_tool_search_multiquery.py tests/tools/test_connector_local_batches.py tests/run_agent/test_tool_executor_contextvar_propagation.py tests/agent/test_tool_executor_checkpoint_paths.py tests/agent/test_inline_tool_executors_memory_args.py tests/run_agent/test_concurrent_interrupt.py --file-retries 0`

Only source, synthetic peer fixture/tests and this sanitized report are published. Historical raw logs/research remain local and untracked. Fixtures do not represent real human decisions. No production database, credentials, session payloads or runtime configuration is included. No listener, production change or deployment was performed.

## Next integration boundaries

Agree shared versioned offline schema before diverging implementations. Keep logical authorization records in a control plane or negotiated extension, not arbitrary parser fields. Separate prepare from possession of the receiver bearer; expose bounded result/artifact references; audit trusted origin adapters; test receiver deduplication and inverse persistence independently. Do not reopen native send until scope verification and the trusted control boundary are implemented and tested.

Coordination: https://git.vauxoo.com/carlosrve/a2a/-/merge_requests/1
