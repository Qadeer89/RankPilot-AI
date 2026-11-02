import base64

from app.connectors import github_pr
from app.connectors.errors import ConnectorError, UnsupportedOperation

CREDENTIALS = github_pr.GitHubCredentials(
    owner="acme", repo="marketing-site", base_branch="main", access_token="ghp_abc123"
)

PAGE_HTML = (
    "<html><head><title>Old Title</title>"
    '<meta name="description" content="Old description"></head>'
    "<body>About us</body></html>"
)


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(payload)

    def json(self):
        return self._payload


def _encode(content: str) -> str:
    return base64.b64encode(content.encode("utf-8")).decode("ascii")


def test_verify_credentials_success(monkeypatch):
    monkeypatch.setattr(github_pr.httpx, "get", lambda *a, **k: _FakeResponse(200, {"id": 1}))
    result = github_pr.verify_credentials(CREDENTIALS)
    assert result["id"] == 1


def test_verify_credentials_network_failure_raises_connector_error_not_httpx_error(monkeypatch):
    import httpx

    def fake_get(*a, **k):
        raise httpx.ConnectError("DNS resolution failed")

    monkeypatch.setattr(github_pr.httpx, "get", fake_get)
    try:
        github_pr.verify_credentials(CREDENTIALS)
        assert False, "expected ConnectorError"
    except ConnectorError:
        pass
    except httpx.ConnectError:
        assert False, "network-level httpx errors must be wrapped as ConnectorError, not leak through"


def test_verify_credentials_failure_raises(monkeypatch):
    monkeypatch.setattr(github_pr.httpx, "get", lambda *a, **k: _FakeResponse(404, {}))
    try:
        github_pr.verify_credentials(CREDENTIALS)
        assert False, "expected ConnectorError"
    except ConnectorError:
        pass


def test_find_target_tries_candidates_until_match(monkeypatch):
    attempted = []

    def fake_get(url, params=None, headers=None, timeout=None):
        attempted.append(url)
        if url.endswith("/contents/about/index.html"):
            return _FakeResponse(200, {"sha": "sha123", "content": _encode(PAGE_HTML)})
        return _FakeResponse(404, {})

    monkeypatch.setattr(github_pr.httpx, "get", fake_get)
    target = github_pr.find_target(CREDENTIALS, "https://example.com/about")
    assert target == {"file_path": "about/index.html", "sha": "sha123", "content": PAGE_HTML}
    # The first candidate ("about.html") should have been tried and missed.
    assert any(u.endswith("/contents/about.html") for u in attempted)


def test_find_target_raises_when_no_convention_matches(monkeypatch):
    monkeypatch.setattr(github_pr.httpx, "get", lambda *a, **k: _FakeResponse(404, {}))
    try:
        github_pr.find_target(CREDENTIALS, "https://example.com/about")
        assert False, "expected ConnectorError"
    except ConnectorError:
        pass


def test_get_current_value_extracts_title_and_description():
    target_ref = {"file_path": "about.html", "sha": "sha123", "content": PAGE_HTML}
    assert github_pr.get_current_value(CREDENTIALS, target_ref, "set_title") == "Old Title"
    assert github_pr.get_current_value(CREDENTIALS, target_ref, "set_meta_description") == "Old description"


def test_apply_change_opens_branch_commit_and_pull_request(monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=None, params=None):
        calls.append(("GET", url, params))
        if url.endswith("/git/ref/heads/main"):
            return _FakeResponse(200, {"object": {"sha": "base-sha"}})
        return _FakeResponse(404, {})

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(("POST", url, json))
        if url.endswith("/git/refs"):
            return _FakeResponse(201, {"ref": json["ref"]})
        if url.endswith("/pulls"):
            return _FakeResponse(201, {"number": 42, "html_url": "https://github.com/acme/marketing-site/pull/42"})
        return _FakeResponse(400, {})

    def fake_put(url, json=None, headers=None, timeout=None):
        calls.append(("PUT", url, json))
        return _FakeResponse(200, {"commit": {"sha": "new-sha"}})

    monkeypatch.setattr(github_pr.httpx, "get", fake_get)
    monkeypatch.setattr(github_pr.httpx, "post", fake_post)
    monkeypatch.setattr(github_pr.httpx, "put", fake_put)

    target_ref = {"file_path": "about.html", "sha": "sha123", "content": PAGE_HTML}
    result = github_pr.apply_change(CREDENTIALS, target_ref, "set_title", "New Title")

    assert result["pr_number"] == 42
    assert result["pr_url"].endswith("/pull/42")
    assert result["branch"].startswith("rankpilot/set_title-")

    put_call = next(c for c in calls if c[0] == "PUT")
    committed_content = base64.b64decode(put_call[2]["content"]).decode("utf-8")
    assert "<title>New Title</title>" in committed_content


def test_apply_change_raises_unsupported_operation_when_tag_missing():
    target_ref = {"file_path": "about.html", "sha": "sha123", "content": "<html><body>No title tag here</body></html>"}
    try:
        github_pr.apply_change(CREDENTIALS, target_ref, "set_title", "New Title")
        assert False, "expected UnsupportedOperation"
    except UnsupportedOperation:
        pass


def test_validate_change_passes_when_diff_matches_and_pr_open(monkeypatch):
    new_html = PAGE_HTML.replace("Old Title", "New Title")

    def fake_get(url, headers=None, timeout=None, params=None):
        if "/contents/" in url:
            return _FakeResponse(200, {"content": _encode(new_html)})
        if "/pulls/42" in url:
            return _FakeResponse(200, {"state": "open"})
        return _FakeResponse(404, {})

    monkeypatch.setattr(github_pr.httpx, "get", fake_get)

    target_ref = {"file_path": "about.html", "sha": "sha123", "content": PAGE_HTML}
    apply_result = {"pr_number": 42, "pr_url": "https://github.com/acme/marketing-site/pull/42", "branch": "rankpilot/set_title-abcd1234"}
    passed, evidence = github_pr.validate_change(CREDENTIALS, target_ref, "set_title", "New Title", apply_result)

    assert passed is True
    assert evidence["pr_state"] == "open"


def test_validate_change_fails_when_pr_closed(monkeypatch):
    new_html = PAGE_HTML.replace("Old Title", "New Title")

    def fake_get(url, headers=None, timeout=None, params=None):
        if "/contents/" in url:
            return _FakeResponse(200, {"content": _encode(new_html)})
        if "/pulls/42" in url:
            return _FakeResponse(200, {"state": "closed"})
        return _FakeResponse(404, {})

    monkeypatch.setattr(github_pr.httpx, "get", fake_get)

    target_ref = {"file_path": "about.html", "sha": "sha123", "content": PAGE_HTML}
    apply_result = {"pr_number": 42, "pr_url": "https://github.com/acme/marketing-site/pull/42", "branch": "rankpilot/set_title-abcd1234"}
    passed, evidence = github_pr.validate_change(CREDENTIALS, target_ref, "set_title", "New Title", apply_result)

    assert passed is False
    assert evidence["pr_state"] == "closed"


def test_rollback_closes_pull_request(monkeypatch):
    closed = {}

    def fake_patch(url, json=None, headers=None, timeout=None):
        closed["url"] = url
        closed["json"] = json
        return _FakeResponse(200, {"number": 42, "state": "closed"})

    monkeypatch.setattr(github_pr.httpx, "patch", fake_patch)

    after_state = {"apply_result": {"pr_number": 42, "pr_url": "...", "branch": "rankpilot/set_title-abcd1234"}}
    result = github_pr.rollback(CREDENTIALS, {"file_path": "about.html"}, "set_title", "Old Title", after_state)

    assert closed["url"].endswith("/pulls/42")
    assert closed["json"] == {"state": "closed"}
    assert result["state"] == "closed"
