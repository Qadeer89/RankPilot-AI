"""GitHub connector for custom-code sites (P1, MASTER_SPEC.md #5:
"GitHub/deployment integration for custom-code sites").

Unlike the CMS connectors (WordPress/Shopify/Webflow), a custom-code
site has no live write API: the "site" is source files in a git repo,
built and deployed by a pipeline this platform doesn't control. So this
connector never writes live. Its one write operation is: open a branch +
commit + pull request with the proposed <title>/meta-description change,
for a human to review and merge — WEBSITE_CONNECTORS.md's
human-in-the-loop principle, taken to its necessary limit for this site
type, since there's no other safe way to ship a change to code.

"Rollback" closes that still-open PR rather than reverting a live
change, since nothing has shipped yet; once a PR merges, reverting is an
ordinary git operation outside this platform's scope.

"Validation" is correspondingly shallower than for a live connector: it
confirms the PR exists, is open, and its branch's file content contains
the expected new value — not that a deployed site now serves it, which
this platform has no way to observe without knowing the deploy pipeline.
This limitation is intentional and documented, not an oversight.

Finds the file to edit by trying a small set of conventional static-site
paths derived from the URL (e.g. "/about/" -> "about.html",
"about/index.html", "pages/about.html", ...). A site that doesn't follow
one of these conventions isn't supported yet — see README.

Authenticates with a GitHub personal access token scoped to the one
repository (never a broad org-wide token).
"""

from __future__ import annotations

import base64
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.connectors.errors import ConnectorError, UnsupportedOperation, safe_request

API_BASE = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS = 15.0

TITLE_RE = re.compile(r"(<title[^>]*>)(.*?)(</title>)", re.IGNORECASE | re.DOTALL)
META_DESCRIPTION_RE = re.compile(
    r'(<meta[^>]+name=["\']description["\'][^>]+content=["\'])(.*?)(["\'])', re.IGNORECASE
)

# Declared capability set (CW-001, addendum §4.3) — see wordpress.py.
SUPPORTED_OPERATIONS = frozenset({"set_title", "set_meta_description"})

# Protected-path denylist (CW-012, addendum §4.2/§9: "Strictly allowlist
# writable fields, file paths and change types", "No secret, environment,
# dependency, infrastructure, authentication or payment code changes as
# SEO fixes"). `_candidate_paths()` only ever generates conventional
# static-page paths today, so none of these would naturally collide --
# this is defense in depth against a future change to that convention
# list, or a repo whose directory layout happens to coincide with one of
# these names, ever resolving to a write here.
PROTECTED_PATH_PREFIXES = (
    ".github/",
    ".git/",
    ".env",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "requirements.txt",
    "poetry.lock",
    "Pipfile",
    "Dockerfile",
    "docker-compose",
    ".npmrc",
    "next.config",
    "vercel.json",
    "netlify.toml",
)


def _is_protected_path(file_path: str) -> bool:
    normalized = file_path.lstrip("/")
    return any(normalized == prefix or normalized.startswith(prefix) for prefix in PROTECTED_PATH_PREFIXES)


@dataclass(frozen=True)
class GitHubCredentials:
    owner: str
    repo: str
    base_branch: str
    access_token: str

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}", "Accept": "application/vnd.github+json"}


def _repo_api_base(credentials: GitHubCredentials) -> str:
    return f"{API_BASE}/repos/{credentials.owner}/{credentials.repo}"


def verify_credentials(credentials: GitHubCredentials) -> dict:
    response = safe_request(
        httpx.get, _repo_api_base(credentials), headers=credentials.headers, timeout=REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code != 200:
        raise ConnectorError(
            f"Could not verify GitHub credentials: HTTP {response.status_code} {response.text[:200]}"
        )
    return response.json()


def _candidate_paths(target_url: str) -> list[str]:
    path = urlsplit(target_url).path.strip("/")
    if not path:
        return ["index.html", "public/index.html", "src/pages/index.html"]
    return [
        f"{path}.html",
        f"{path}/index.html",
        f"pages/{path}.html",
        f"public/{path}.html",
        f"src/pages/{path}.html",
    ]


def find_target(credentials: GitHubCredentials, target_url: str) -> dict:
    """Try each conventional static-site path until one resolves to a
    real file, and return its path/sha/decoded content.
    """
    for candidate in _candidate_paths(target_url):
        if _is_protected_path(candidate):
            continue  # never even ask about a protected path, let alone write to it
        response = safe_request(
            httpx.get,
            f"{_repo_api_base(credentials)}/contents/{candidate}",
            headers=credentials.headers,
            params={"ref": credentials.base_branch},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            body = response.json()
            if isinstance(body, list):
                continue  # candidate matched a directory, not a file
            content = base64.b64decode(body["content"]).decode("utf-8")
            return {"file_path": candidate, "sha": body["sha"], "content": content}
    raise ConnectorError(
        f"No source file found for URL {target_url} using known static-site conventions."
    )


def extract_value(operation: str, html: str) -> str:
    """Public so a post-deploy verification step (CW-014) can extract the
    same way from freshly-crawled live HTML, not just this connector's
    own file content."""
    if operation == "set_title":
        match = TITLE_RE.search(html)
        return match.group(2) if match else ""
    if operation == "set_meta_description":
        match = META_DESCRIPTION_RE.search(html)
        return match.group(2) if match else ""
    raise ValueError(f"Unsupported operation: {operation}")


def get_current_value(credentials: GitHubCredentials, target_ref: dict, operation: str) -> str:
    return extract_value(operation, target_ref["content"])


def _replace(operation: str, content: str, new_value: str) -> str:
    if operation == "set_title":
        if not TITLE_RE.search(content):
            raise UnsupportedOperation("No <title> tag found in this file.")
        return TITLE_RE.sub(lambda m: m.group(1) + new_value + m.group(3), content, count=1)
    if operation == "set_meta_description":
        if not META_DESCRIPTION_RE.search(content):
            raise UnsupportedOperation("No meta description tag found in this file.")
        return META_DESCRIPTION_RE.sub(lambda m: m.group(1) + new_value + m.group(3), content, count=1)
    raise ValueError(f"Unsupported operation: {operation}")


def _get_branch_head_sha(credentials: GitHubCredentials, branch: str) -> str:
    response = safe_request(
        httpx.get,
        f"{_repo_api_base(credentials)}/git/ref/heads/{branch}",
        headers=credentials.headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise ConnectorError(f"Could not resolve branch {branch}: HTTP {response.status_code} {response.text[:200]}")
    return response.json()["object"]["sha"]


def _create_branch(credentials: GitHubCredentials, branch_name: str, from_sha: str) -> None:
    response = safe_request(
        httpx.post,
        f"{_repo_api_base(credentials)}/git/refs",
        json={"ref": f"refs/heads/{branch_name}", "sha": from_sha},
        headers=credentials.headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 201:
        raise ConnectorError(f"Could not create branch {branch_name}: HTTP {response.status_code} {response.text[:200]}")


def _commit_file(credentials: GitHubCredentials, file_path: str, new_content: str, sha: str, branch: str, message: str) -> None:
    response = safe_request(
        httpx.put,
        f"{_repo_api_base(credentials)}/contents/{file_path}",
        json={
            "message": message,
            "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
            "sha": sha,
            "branch": branch,
        },
        headers=credentials.headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code not in (200, 201):
        raise ConnectorError(
            f"Could not commit {file_path} to {branch}: HTTP {response.status_code} {response.text[:200]}"
        )


def _open_pull_request(credentials: GitHubCredentials, branch: str, title: str, body: str) -> dict:
    response = safe_request(
        httpx.post,
        f"{_repo_api_base(credentials)}/pulls",
        json={"title": title, "head": branch, "base": credentials.base_branch, "body": body},
        headers=credentials.headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 201:
        raise ConnectorError(f"Could not open pull request: HTTP {response.status_code} {response.text[:200]}")
    return response.json()


def close_pull_request(credentials: GitHubCredentials, pr_number: int) -> dict:
    response = safe_request(
        httpx.patch,
        f"{_repo_api_base(credentials)}/pulls/{pr_number}",
        json={"state": "closed"},
        headers=credentials.headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise ConnectorError(f"Could not close pull request #{pr_number}: HTTP {response.status_code} {response.text[:200]}")
    return response.json()


def apply_change(credentials: GitHubCredentials, target_ref: dict, operation: str, new_value: str) -> dict:
    if _is_protected_path(target_ref["file_path"]):
        # Should be unreachable -- find_target() already filters these out
        # -- but this is the actual write call, so it gets its own,
        # independent guard rather than trusting an earlier check.
        raise UnsupportedOperation(f"Refusing to write to protected path: {target_ref['file_path']}")

    new_content = _replace(operation, target_ref["content"], new_value)

    branch_name = f"rankpilot/{operation}-{uuid.uuid4().hex[:8]}"
    base_sha = _get_branch_head_sha(credentials, credentials.base_branch)
    _create_branch(credentials, branch_name, base_sha)
    _commit_file(
        credentials,
        target_ref["file_path"],
        new_content,
        target_ref["sha"],
        branch_name,
        f"RankPilot AI: update {operation} on {target_ref['file_path']}",
    )
    pull_request = _open_pull_request(
        credentials,
        branch_name,
        title=f"RankPilot AI: {operation} update",
        body=(
            f"Automated SEO change proposed by RankPilot AI for `{target_ref['file_path']}`.\n\n"
            f"Operation: `{operation}`\nNew value: `{new_value}`\n\n"
            "Review the diff and merge to ship this change — RankPilot AI does not merge "
            "or deploy on custom-code sites."
        ),
    )
    return {"pr_number": pull_request["number"], "pr_url": pull_request["html_url"], "branch": branch_name}


def get_combined_status(credentials: GitHubCredentials, ref: str) -> str:
    """The repo's configured CI/build/lint/type-check result for `ref`
    (CW-013, addendum §4.2 "Read CI status"): `"success"`, `"failure"`,
    `"pending"`, or `"no_checks"` if nothing reports status yet -- either
    the repo has no CI configured, or checks haven't started running yet.

    This is a single snapshot, not a wait-for-completion poll: CI
    typically hasn't finished (often hasn't started) by the moment this
    connector opens the PR and calls validate_change() right after, so
    `"pending"`/`"no_checks"` do not by themselves fail validation here --
    only an already-reported `"failure"` does. Waiting for CI to actually
    finish before reporting final validation needs an async follow-up
    (e.g. a scheduled re-check), which is not implemented yet; treat a
    `"pending"`/`"no_checks"` result as "not yet proven safe", not as "safe".
    """
    response = safe_request(
        httpx.get,
        f"{_repo_api_base(credentials)}/commits/{ref}/status",
        headers=credentials.headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        return "no_checks"
    body = response.json()
    if body.get("total_count", 0) == 0:
        return "no_checks"
    return body.get("state", "pending")


def validate_change(
    credentials: GitHubCredentials, target_ref: dict, operation: str, expected_value: str, apply_result: dict
) -> tuple[bool, dict]:
    branch = apply_result["branch"]
    response = safe_request(
        httpx.get,
        f"{_repo_api_base(credentials)}/contents/{target_ref['file_path']}",
        headers=credentials.headers,
        params={"ref": branch},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        return False, {"error": f"Could not re-fetch {target_ref['file_path']} on branch {branch}"}

    content = base64.b64decode(response.json()["content"]).decode("utf-8")
    actual = extract_value(operation, content)

    pr_response = safe_request(
        httpx.get,
        f"{_repo_api_base(credentials)}/pulls/{apply_result['pr_number']}",
        headers=credentials.headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    pr_state = pr_response.json().get("state") if pr_response.status_code == 200 else "unknown"
    ci_status = get_combined_status(credentials, branch)

    # A reported failure blocks promotion outright (CW-013: "Failed check
    # blocks promotion"). Pending/no-checks don't block here -- see
    # get_combined_status()'s docstring on why this is a snapshot, not a
    # guarantee CI has actually passed.
    passed = actual == expected_value and pr_state == "open" and ci_status != "failure"
    return passed, {
        "expected": expected_value,
        "actual": actual,
        "pr_number": apply_result["pr_number"],
        "pr_url": apply_result["pr_url"],
        "pr_state": pr_state,
        "ci_status": ci_status,
    }


def rollback(
    credentials: GitHubCredentials, target_ref: dict, operation: str, before_value: str, after_state: dict
) -> dict:
    pr_number = after_state["apply_result"]["pr_number"]
    return close_pull_request(credentials, pr_number)
