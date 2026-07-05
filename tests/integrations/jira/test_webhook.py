from __future__ import annotations

import logging

from integrations.jira.webhook import handle_transition


class TestHandleTransition:
    def test_logs_issue_key_and_status(self, caplog):
        payload = {
            "issue": {"key": "INFRA-42"},
            "transition": {"to": {"name": "Approved"}},
        }
        with caplog.at_level(logging.INFO):
            handle_transition(payload)
        assert "INFRA-42" in caplog.text
        assert "Approved" in caplog.text

    def test_missing_fields_logs_unknown(self, caplog):
        with caplog.at_level(logging.INFO):
            handle_transition({})
        assert "UNKNOWN" in caplog.text

    def test_does_not_raise(self):
        handle_transition(
            {
                "issue": {"key": "X-1"},
                "transition": {"to": {"name": "Done"}},
            }
        )
