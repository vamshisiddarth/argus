from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from integrations.jira.client import JiraClient, _adf_paragraph

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> JiraClient:
    return JiraClient(
        base_url="https://test.atlassian.net",
        email="bot@test.com",
        api_token="secret",
    )


def _mock_response(json_data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    resp.content = b"content"
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    @patch("integrations.jira.client.requests.get")
    def test_returns_issues_list(self, mock_get, client):
        mock_get.return_value = _mock_response({"issues": [{"key": "INFRA-1"}]})
        result = client.search("project=INFRA")
        assert result == [{"key": "INFRA-1"}]

    @patch("integrations.jira.client.requests.get")
    def test_empty_result(self, mock_get, client):
        mock_get.return_value = _mock_response({"issues": []})
        result = client.search("project=INFRA AND labels=notexist")
        assert result == []

    @patch("integrations.jira.client.requests.get")
    def test_passes_jql_as_param(self, mock_get, client):
        mock_get.return_value = _mock_response({"issues": []})
        client.search("project=INFRA", max_results=5)
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["jql"] == "project=INFRA"
        assert kwargs["params"]["maxResults"] == 5

    @patch("integrations.jira.client.requests.get")
    def test_raises_on_http_error(self, mock_get, client):
        resp = _mock_response({}, 401)
        resp.raise_for_status.side_effect = requests.HTTPError("401")
        mock_get.return_value = resp
        with pytest.raises(requests.HTTPError):
            client.search("project=INFRA")


# ---------------------------------------------------------------------------
# create_issue
# ---------------------------------------------------------------------------


class TestCreateIssue:
    @patch("integrations.jira.client.requests.post")
    def test_returns_key_in_response(self, mock_post, client):
        mock_post.return_value = _mock_response({"key": "INFRA-42", "id": "10001"})
        result = client.create_issue({"project": {"key": "INFRA"}, "summary": "test"})
        assert result["key"] == "INFRA-42"

    @patch("integrations.jira.client.requests.post")
    def test_raises_on_http_error(self, mock_post, client):
        resp = _mock_response({}, 400)
        resp.raise_for_status.side_effect = requests.HTTPError("400")
        mock_post.return_value = resp
        with pytest.raises(requests.HTTPError):
            client.create_issue({})


# ---------------------------------------------------------------------------
# add_comment
# ---------------------------------------------------------------------------


class TestAddComment:
    @patch("integrations.jira.client.requests.post")
    def test_posts_to_comment_endpoint(self, mock_post, client):
        resp = MagicMock()
        resp.content = b""
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp
        client.add_comment("INFRA-1", "hello")
        url = mock_post.call_args[0][0]
        assert "/issue/INFRA-1/comment" in url

    @patch("integrations.jira.client.requests.post")
    def test_comment_body_is_adf(self, mock_post, client):
        resp = MagicMock()
        resp.content = b""
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp
        client.add_comment("INFRA-1", "test text")
        payload = mock_post.call_args[1]["json"]
        assert payload["body"]["type"] == "doc"


# ---------------------------------------------------------------------------
# issue_url
# ---------------------------------------------------------------------------


class TestIssueUrl:
    def test_constructs_browse_url(self, client):
        assert (
            client.issue_url("INFRA-99") == "https://test.atlassian.net/browse/INFRA-99"
        )

    def test_strips_trailing_slash(self):
        c = JiraClient("https://test.atlassian.net/", "e", "t")
        assert c.issue_url("X-1") == "https://test.atlassian.net/browse/X-1"


# ---------------------------------------------------------------------------
# _adf_paragraph
# ---------------------------------------------------------------------------


class TestAdfParagraph:
    def test_returns_doc_type(self):
        doc = _adf_paragraph("hello")
        assert doc["type"] == "doc"
        assert doc["version"] == 1

    def test_contains_text(self):
        doc = _adf_paragraph("hello world")
        text = doc["content"][0]["content"][0]["text"]
        assert text == "hello world"
