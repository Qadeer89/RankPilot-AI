"""GitHub connector additions for opt-in "auto-merge on CI success"
(see app/tasks/scheduler.py::poll_and_merge_github_prs): a CI-status
check that covers GitHub Actions' Check Runs API (not just the legacy
Commit Status API), plus get_pull_request/merge_pull_request.
"""

from app.connectors import github_pr
from app.connectors.errors import ConnectorError

CREDENTIALS = github_pr.GitHubCredentials(
    owner="acme", repo="marketing-site", base_branch="main", access_token="ghp_abc123"
)


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(payload)

    def json(self):
        return self._payload


def _fake_get(status_body=None, status_code_for_status=200, check_runs=None, check_runs_code=200):
    def fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/status"):
            return _FakeResponse(status_code_for_status, status_body if status_body is not None else {})
        if url.endswith("/check-runs"):
            return _FakeResponse(check_runs_code, {"check_runs": check_runs} if check_runs is not None else {})
        return _FakeResponse(404, {})

    return fake_get


def test_combined_status_no_checks_when_both_sources_empty(monkeypatch):
    monkeypatch.setattr(github_pr.httpx, "get", _fake_get(status_body={"total_count": 0}, check_runs=[]))
    assert github_pr.get_combined_status(CREDENTIALS, "abc123") == "no_checks"


def test_combined_status_success_from_check_runs_when_no_legacy_status(monkeypatch):
    # A repo whose only CI is a GitHub Actions workflow reports nothing
    # via the legacy Commit Status API at all -- this must still read
    # as "success", not "no_checks".
    monkeypatch.setattr(
        github_pr.httpx,
        "get",
        _fake_get(
            status_body={"total_count": 0},
            check_runs=[{"status": "completed", "conclusion": "success"}],
        ),
    )
    assert github_pr.get_combined_status(CREDENTIALS, "abc123") == "success"


def test_combined_status_failure_from_check_runs_wins_over_legacy_success(monkeypatch):
    monkeypatch.setattr(
        github_pr.httpx,
        "get",
        _fake_get(
            status_body={"total_count": 1, "state": "success"},
            check_runs=[{"status": "completed", "conclusion": "failure"}],
        ),
    )
    assert github_pr.get_combined_status(CREDENTIALS, "abc123") == "failure"


def test_combined_status_pending_while_check_run_still_running(monkeypatch):
    monkeypatch.setattr(
        github_pr.httpx,
        "get",
        _fake_get(status_body={"total_count": 0}, check_runs=[{"status": "in_progress", "conclusion": None}]),
    )
    assert github_pr.get_combined_status(CREDENTIALS, "abc123") == "pending"


def test_combined_status_url_encodes_branch_name_slashes(monkeypatch):
    # Real branch names look like "rankpilot/set_title-abc123" -- an
    # unencoded "/" here turns into an extra URL path segment, which
    # GitHub 404s (silently misread as "no_checks" regardless of CI's
    # actual state). Every call this connector makes with a branch-name
    # ref must URL-encode it.
    requested_urls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        requested_urls.append(url)
        return _FakeResponse(200, {"total_count": 0})

    monkeypatch.setattr(github_pr.httpx, "get", fake_get)
    github_pr.get_combined_status(CREDENTIALS, "rankpilot/set_title-abc123")

    assert requested_urls, "expected at least one request"
    for url in requested_urls:
        assert "rankpilot/set_title-abc123" not in url
        assert "rankpilot%2Fset_title-abc123" in url


def test_combined_status_legacy_failure_still_works(monkeypatch):
    monkeypatch.setattr(
        github_pr.httpx,
        "get",
        _fake_get(status_body={"total_count": 1, "state": "failure"}, check_runs=[]),
    )
    assert github_pr.get_combined_status(CREDENTIALS, "abc123") == "failure"


def test_get_pull_request_returns_body(monkeypatch):
    monkeypatch.setattr(
        github_pr.httpx,
        "get",
        lambda *a, **k: _FakeResponse(200, {"number": 5, "state": "open", "head": {"ref": "rankpilot/x"}}),
    )
    pr = github_pr.get_pull_request(CREDENTIALS, 5)
    assert pr["state"] == "open"
    assert pr["head"]["ref"] == "rankpilot/x"


def test_get_pull_request_raises_on_error(monkeypatch):
    monkeypatch.setattr(github_pr.httpx, "get", lambda *a, **k: _FakeResponse(404, {"message": "Not Found"}))
    try:
        github_pr.get_pull_request(CREDENTIALS, 5)
        assert False, "expected ConnectorError"
    except ConnectorError:
        pass


def test_merge_pull_request_success(monkeypatch):
    monkeypatch.setattr(github_pr.httpx, "put", lambda *a, **k: _FakeResponse(200, {"merged": True, "sha": "abc"}))
    result = github_pr.merge_pull_request(CREDENTIALS, 5)
    assert result["merged"] is True


def test_get_branch_head_sha_url_encodes_branch_name_slashes(monkeypatch):
    requested_urls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        requested_urls.append(url)
        return _FakeResponse(200, {"object": {"sha": "abc123"}})

    monkeypatch.setattr(github_pr.httpx, "get", fake_get)
    sha = github_pr._get_branch_head_sha(CREDENTIALS, "release/v2")

    assert sha == "abc123"
    assert requested_urls == [f"{github_pr._repo_api_base(CREDENTIALS)}/git/ref/heads/release%2Fv2"]


def test_merge_pull_request_raises_on_failure(monkeypatch):
    monkeypatch.setattr(
        github_pr.httpx, "put", lambda *a, **k: _FakeResponse(405, {"message": "Pull Request is not mergeable"})
    )
    try:
        github_pr.merge_pull_request(CREDENTIALS, 5)
        assert False, "expected ConnectorError"
    except ConnectorError:
        pass
