"""
Thin Jira REST API wrapper — no Jira SDK, plain requests.

Covers only the operations Argus needs:
  - search issues by JQL
  - create issue
  - add comment
  - get issue (fetch description for snapshot extraction)
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str) -> None:
        self._base = base_url.rstrip("/")
        self._auth = (email, api_token)
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, jql: str, max_results: int = 10) -> list[dict[str, Any]]:
        """Return list of issue dicts matching the JQL query."""
        resp = self._get(
            "/rest/api/3/search",
            params={
                "jql": jql,
                "maxResults": max_results,
                "fields": "summary,status,description",
            },
        )
        return resp.get("issues", [])

    def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Create an issue and return the response dict (contains key + self URL)."""
        resp = self._post("/rest/api/3/issue", json={"fields": fields})
        return resp

    def add_comment(self, issue_key: str, body: str) -> None:
        """Add a plain-text comment to an issue."""
        self._post(
            f"/rest/api/3/issue/{issue_key}/comment",
            json={"body": _adf_paragraph(body)},
        )

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        """Fetch a single issue by key."""
        return self._get(
            f"/rest/api/3/issue/{issue_key}",
            params={"fields": "summary,status,description"},
        )

    def issue_url(self, issue_key: str) -> str:
        return f"{self._base}/browse/{issue_key}"

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        resp = requests.get(
            self._base + path,
            auth=self._auth,
            headers=self._headers,
            params=params,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json: dict | None = None) -> dict[str, Any]:
        resp = requests.post(
            self._base + path,
            auth=self._auth,
            headers=self._headers,
            json=json,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        if resp.content:
            return resp.json()
        return {}


def _adf_paragraph(text: str) -> dict[str, Any]:
    """Wrap plain text in Atlassian Document Format (ADF) for API v3."""
    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }
