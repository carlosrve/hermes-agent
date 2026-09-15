import unittest
from unittest.mock import patch

from tui_gateway.methods_prompt import build_a2a_approval_event


class FixtureTransport:
    def __init__(self, user_id="human-1", provider="desktop"):
        self.auth_identity = {"user_id": user_id, "provider": provider}
        self.closed = False


class A2AApprovalSeamTests(unittest.TestCase):
    def setUp(self):
        self.transport = FixtureTransport()
        self.session = {"session_key": "session-owner", "transport": self.transport}
        self.pending = [{"request_id": "request-owner", "choice": None}]

    def _event(self, params=None, session=None, transport=None):
        return build_a2a_approval_event(
            session or self.session,
            {"a2a_event": True, "request_id": "request-owner", **(params or {})},
            transport=transport or self.transport,
        )

    @patch("tools.approval.list_gateway_approvals")
    def test_owner_gets_callback_event_without_resolving_queue(self, approvals):
        approvals.return_value = self.pending
        event = self._event()
        self.assertEqual(event["type"], "a2a.approval.requested")
        self.assertEqual(event["session_id"], "session-owner")
        self.assertTrue(event["callback_required"])
        self.assertFalse(event["human_decision"])
        approvals.assert_called_once_with("session-owner")

    @patch("tools.approval.list_gateway_approvals")
    def test_stale_session_and_request_from_other_session_are_rejected(self, approvals):
        approvals.side_effect = lambda key: (
            [{"request_id": "request-other"}] if key == "session-stale"
            else self.pending)
        stale = {"session_key": "session-stale", "transport": self.transport}
        self.assertIsNone(self._event(session=stale))
        # The caller cannot use a request observed in another session to select
        # this owner's queue; the queue must match this session's exact ID.
        self.assertIsNone(self._event(params={"request_id": "request-other"}))

    @patch("tools.approval.list_gateway_approvals")
    def test_other_transport_profile_and_all_are_rejected(self, approvals):
        approvals.return_value = self.pending
        other = FixtureTransport(user_id="other", provider="desktop")
        self.assertIsNone(self._event(transport=other))
        self.assertIsNone(self._event(params={"all": True}))
        self.assertIsNone(self._event(transport=FixtureTransport(user_id="", provider="desktop")))
        approvals.assert_not_called()

    @patch("tools.approval.list_gateway_approvals")
    def test_seam_is_opt_in_and_never_accepts_worker_approval_fields(self, approvals):
        approvals.return_value = self.pending
        self.assertIsNone(build_a2a_approval_event(
            self.session, {"request_id": "request-owner", "choice": "approve"}, self.transport))
        event = self._event(params={"approval_id": "worker-chosen", "choice": "approve"})
        self.assertNotIn("approval_id", event)
        self.assertNotIn("choice", event)
        self.assertNotIn("decision", event)


if __name__ == "__main__":
    unittest.main()
