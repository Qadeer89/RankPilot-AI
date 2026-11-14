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
"about/index.html", "pages/about.html", ...), plus Next.js App Router
conventions (e.g. "/about/" -> "app/about/page.tsx"). A site that
doesn't follow one of these conventions isn't supported yet — see
README.

A Next.js page's title/meta-description/canonical aren't raw HTML tags
to regex-replace -- they're declared in an `export const metadata`
object. Two shapes are supported there: a plain string/template literal
(edited directly), or a single `${identifier.field}` interpolation
where `identifier` is bound via `const identifier = importedArray.find(x
=> x.slug === "...")` -- common on sites whose page copy lives in a
shared data file keyed by slug, resolved by following the import and
editing the matching entry there instead. Anything else fails clearly
rather than guessing which value to change.

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
CANONICAL_RE = re.compile(
    r'(<link[^>]+rel=["\']canonical["\'][^>]+href=["\'])(.*?)(["\'])', re.IGNORECASE
)
SCHEMA_SCRIPT_RE = re.compile(
    r'(<script[^>]+type=["\']application/ld\+json["\'][^>]*>)(.*?)(</script>)',
    re.IGNORECASE | re.DOTALL,
)
HEAD_CLOSE_RE = re.compile(r"</head>", re.IGNORECASE)

# Next.js App Router metadata support -- see module docstring.
TSX_METADATA_FIELD_KEYS = {
    "set_title": "title",
    "set_meta_description": "description",
    "set_canonical": "canonical",
}
_METADATA_EXPORT_RE = re.compile(r"export\s+const\s+metadata\s*(?::\s*\w+\s*)?=\s*\{")
_TEMPLATE_EXPR_RE = re.compile(r"\$\{\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\}")
_FIND_BINDING_RE_TEMPLATE = (
    r'const\s+{identifier}\s*=\s*([A-Za-z_]\w*)\s*\.\s*find\(\s*\(?\s*\w+\s*\)?\s*=>\s*'
    r'\w+\.(\w+)\s*===?\s*["\']([^"\']+)["\']\s*\)'
)

# Declared capability set (CW-001, addendum §4.3) — see wordpress.py.
# set_canonical and set_schema_json are reliable here, unlike the CMS
# connectors: a direct regex replace of the file's own <link
# rel="canonical"> tag or <script type="application/ld+json"> block,
# the same mechanism set_title/set_meta_description already use
# (RankPilot AI Phase 3 "Canonical Tag Automation" / "Schema Markup
# Automation").
SUPPORTED_OPERATIONS = frozenset(
    {"set_title", "set_meta_description", "set_canonical", "set_schema_json"}
)

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
        return [
            "index.html",
            "public/index.html",
            "src/pages/index.html",
            "app/page.tsx",
            "src/app/page.tsx",
            "app/page.jsx",
            "src/app/page.jsx",
        ]
    return [
        f"{path}.html",
        f"{path}/index.html",
        f"pages/{path}.html",
        f"public/{path}.html",
        f"src/pages/{path}.html",
        f"app/{path}/page.tsx",
        f"src/app/{path}/page.tsx",
        f"app/{path}/page.jsx",
        f"src/app/{path}/page.jsx",
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


def _is_tsx_source(file_path: str) -> bool:
    return file_path.endswith((".tsx", ".jsx"))


def _find_balanced_block(content: str, open_brace_index: int) -> tuple[int, int]:
    """`open_brace_index` points at an already-matched '{'. Returns the
    (start, end) span of the block's inner content, exclusive of the
    braces themselves."""
    depth = 1
    i = open_brace_index + 1
    while i < len(content) and depth > 0:
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
        i += 1
    return open_brace_index + 1, i - 1


def _field_value_pattern(key: str) -> re.Pattern:
    # A field's value is either a quoted string/template literal, or --
    # common when the field mirrors another variable's property, e.g.
    # `description: service.metaDescription,` with no quotes at all --
    # a bare `identifier.field` expression.
    return re.compile(
        rf"{re.escape(key)}\s*:\s*(`[^`]*`|\"[^\"]*\"|'[^']*'|[A-Za-z_]\w*\.[A-Za-z_]\w*)"
    )


def _find_field_in_block(content: str, block_span: tuple[int, int], key: str) -> tuple[int, int, str] | None:
    start, end = block_span
    match = _field_value_pattern(key).search(content, start, end)
    if match is None:
        return None
    return match.start(1), match.end(1), match.group(1)


def _is_plain_literal(raw_value: str) -> bool:
    if raw_value.startswith("`"):
        return "${" not in raw_value[1:-1]
    if raw_value[0] in "\"'":
        return True
    return False  # a bare `identifier.field` expression, no quotes at all


def _bare_expression_ref(raw_value: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"([A-Za-z_]\w*)\.([A-Za-z_]\w*)", raw_value)
    return match.groups() if match else None


def _unquote(raw_value: str) -> str:
    return raw_value[1:-1]


def _requote(raw_value: str, new_value: str) -> str:
    return f"{raw_value[0]}{new_value}{raw_value[0]}"


def _find_metadata_block(content: str) -> tuple[int, int]:
    match = _METADATA_EXPORT_RE.search(content)
    if match is None:
        raise UnsupportedOperation("No `export const metadata` object found in this file.")
    return _find_balanced_block(content, match.end() - 1)


def _find_entry_span(content: str, slug_field: str, slug_value: str) -> tuple[int, int]:
    entry_match = re.search(rf'{re.escape(slug_field)}\s*:\s*["\']{re.escape(slug_value)}["\']', content)
    if entry_match is None:
        raise UnsupportedOperation(f'Could not find an entry with `{slug_field}: "{slug_value}"`.')
    open_brace = content.rfind("{", 0, entry_match.start())
    if open_brace == -1:
        raise UnsupportedOperation(f'Could not locate the object literal containing `{slug_field}: "{slug_value}"`.')
    return _find_balanced_block(content, open_brace)


def _resolve_data_entry_reference(
    credentials: GitHubCredentials, page_content: str, identifier: str, attr: str
) -> dict:
    """`page_content` is the page.tsx source. Finds `const <identifier> =
    <array>.find(x => x.<slug_field> === "<slug>")`, follows the import
    of <array> to its source file, and returns a target_ref for that
    file annotated with enough information to locate the matching
    entry's `<attr>` field fresh on any later fetch of that file's
    content (never cached absolute offsets, which an edit would shift).
    """
    binding_pattern = _FIND_BINDING_RE_TEMPLATE.format(identifier=re.escape(identifier))
    binding_match = re.search(binding_pattern, page_content)
    if binding_match is None:
        raise UnsupportedOperation(
            f"Could not resolve `{identifier}.{attr}`: no `const {identifier} = <array>.find(...)` "
            "binding found in this file."
        )
    array_name, slug_field, slug_value = binding_match.groups()

    import_match = re.search(
        rf'import\s*\{{[^}}]*\b{re.escape(array_name)}\b[^}}]*\}}\s*from\s*["\'](.+?)["\']', page_content
    )
    if import_match is None:
        raise UnsupportedOperation(f"Could not resolve where `{array_name}` is imported from.")
    module_path = import_match.group(1)
    if not module_path.startswith("@/"):
        raise UnsupportedOperation(
            f"Cannot resolve non-alias import path `{module_path}` -- only the `@/` -> repo-root "
            "alias convention is supported."
        )
    relative_path = module_path[2:]

    for ext in (".ts", ".tsx", ".js", ".jsx"):
        candidate = f"{relative_path}{ext}"
        response = safe_request(
            httpx.get,
            f"{_repo_api_base(credentials)}/contents/{candidate}",
            headers=credentials.headers,
            params={"ref": credentials.base_branch},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            body = response.json()
            if not isinstance(body, list):
                return {
                    "file_path": candidate,
                    "sha": body["sha"],
                    "content": base64.b64decode(body["content"]).decode("utf-8"),
                    "_tsx_slug_field": slug_field,
                    "_tsx_slug_value": slug_value,
                    "_tsx_field_key": attr,
                }
    raise UnsupportedOperation(f"Could not find the data file imported as `{module_path}`.")


def _resolve_tsx_target(credentials: GitHubCredentials, target_ref: dict, operation: str) -> dict:
    """Given a target_ref pointing at a .tsx/.jsx page and the operation
    to perform, returns the target_ref actually holding the value to
    read/write: either `target_ref` itself annotated in place (a plain
    literal in the page's own metadata export) or a different file's ref
    (a value resolved from imported data). Memoized on `target_ref` so
    repeated calls across get_current_value/apply_change/validate_change
    -- which all receive the same dict for one execute_task call -- see
    the same resolution and never re-fetch it.
    """
    if "_tsx_resolved" in target_ref:
        return target_ref["_tsx_resolved"]

    field_key = TSX_METADATA_FIELD_KEYS.get(operation)
    if field_key is None:
        raise UnsupportedOperation(f"Operation {operation} is not supported for Next.js source files.")

    block_span = _find_metadata_block(target_ref["content"])
    found = _find_field_in_block(target_ref["content"], block_span, field_key)
    if found is None:
        raise UnsupportedOperation(
            f"No `{field_key}:` field found in the metadata export of {target_ref['file_path']}."
        )
    _, _, raw_value = found

    if _is_plain_literal(raw_value):
        resolved = dict(target_ref)
        resolved["_tsx_mode"] = "metadata_literal"
        resolved["_tsx_field_key"] = field_key
        target_ref["_tsx_resolved"] = resolved
        return resolved

    # A template can have more than one `${...}` (e.g. `` `${service.metaTitle} |
    # ${siteConfig.name}` `` -- a per-entry value next to a static site name) --
    # only the interpolation(s) actually bound via a `.find()` lookup are
    # candidates to resolve; a reference to an unrelated constant like
    # `siteConfig.name` is simply left alone (nothing here ever touches
    # page.tsx itself in this mode, only the resolved data file). A bare
    # `identifier.field` (no quotes/backticks at all, e.g.
    # `description: service.metaDescription`) is the same idea with
    # exactly one candidate.
    if raw_value.startswith("`"):
        exprs = _TEMPLATE_EXPR_RE.findall(raw_value[1:-1])
    else:
        bare = _bare_expression_ref(raw_value)
        exprs = [bare] if bare else []
    resolvable = [
        (identifier, attr)
        for identifier, attr in exprs
        if re.search(_FIND_BINDING_RE_TEMPLATE.format(identifier=re.escape(identifier)), target_ref["content"])
    ]
    if len(resolvable) != 1:
        raise UnsupportedOperation(
            f"The `{field_key}` value in {target_ref['file_path']} is computed from a template with "
            f"{'no' if not resolvable else 'more than one'} data-file-resolvable `${{identifier.field}}` "
            "reference -- RankPilot AI only edits a plain literal or a single such reference."
        )
    identifier, attr = resolvable[0]
    resolved = _resolve_data_entry_reference(credentials, target_ref["content"], identifier, attr)
    resolved["_tsx_mode"] = "data_entry"
    target_ref["_tsx_resolved"] = resolved
    return resolved


def _extract_tsx_value(resolved_ref: dict) -> str:
    content = resolved_ref["content"]
    if resolved_ref["_tsx_mode"] == "metadata_literal":
        block_span = _find_metadata_block(content)
    else:
        block_span = _find_entry_span(content, resolved_ref["_tsx_slug_field"], resolved_ref["_tsx_slug_value"])
    found = _find_field_in_block(content, block_span, resolved_ref["_tsx_field_key"])
    if found is None:
        return ""
    _, _, raw_value = found
    return _unquote(raw_value)


def _replace_tsx_value(resolved_ref: dict, new_value: str) -> str:
    content = resolved_ref["content"]
    if resolved_ref["_tsx_mode"] == "metadata_literal":
        block_span = _find_metadata_block(content)
    else:
        block_span = _find_entry_span(content, resolved_ref["_tsx_slug_field"], resolved_ref["_tsx_slug_value"])
    found = _find_field_in_block(content, block_span, resolved_ref["_tsx_field_key"])
    if found is None:
        raise UnsupportedOperation(f"No `{resolved_ref['_tsx_field_key']}:` field found to update.")
    start, end, raw_value = found
    new_raw = _requote(raw_value, new_value)
    return content[:start] + new_raw + content[end:]


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
    if operation == "set_canonical":
        match = CANONICAL_RE.search(html)
        return match.group(2) if match else ""
    if operation == "set_schema_json":
        match = SCHEMA_SCRIPT_RE.search(html)
        return match.group(2).strip() if match else ""
    raise ValueError(f"Unsupported operation: {operation}")


def get_current_value(credentials: GitHubCredentials, target_ref: dict, operation: str) -> str:
    if _is_tsx_source(target_ref["file_path"]):
        resolved = _resolve_tsx_target(credentials, target_ref, operation)
        return _extract_tsx_value(resolved)
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
    if operation == "set_canonical":
        if not CANONICAL_RE.search(content):
            raise UnsupportedOperation("No canonical <link> tag found in this file.")
        return CANONICAL_RE.sub(lambda m: m.group(1) + new_value + m.group(3), content, count=1)
    if operation == "set_schema_json":
        if SCHEMA_SCRIPT_RE.search(content):
            return SCHEMA_SCRIPT_RE.sub(lambda m: m.group(1) + new_value + m.group(3), content, count=1)
        if not HEAD_CLOSE_RE.search(content):
            raise UnsupportedOperation("No </head> tag found to insert structured data into.")
        new_block = f'<script type="application/ld+json">{new_value}</script>\n'
        return HEAD_CLOSE_RE.sub(new_block + "</head>", content, count=1)
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
    if _is_tsx_source(target_ref["file_path"]):
        resolved = _resolve_tsx_target(credentials, target_ref, operation)
        file_path, sha = resolved["file_path"], resolved["sha"]
        new_content = _replace_tsx_value(resolved, new_value)
    else:
        file_path, sha = target_ref["file_path"], target_ref["sha"]
        new_content = _replace(operation, target_ref["content"], new_value)

    if _is_protected_path(file_path):
        # Should be unreachable -- find_target() already filters these out
        # -- but this is the actual write call, so it gets its own,
        # independent guard rather than trusting an earlier check.
        raise UnsupportedOperation(f"Refusing to write to protected path: {file_path}")

    branch_name = f"rankpilot/{operation}-{uuid.uuid4().hex[:8]}"
    base_sha = _get_branch_head_sha(credentials, credentials.base_branch)
    _create_branch(credentials, branch_name, base_sha)
    _commit_file(
        credentials,
        file_path,
        new_content,
        sha,
        branch_name,
        f"RankPilot AI: update {operation} on {file_path}",
    )
    pull_request = _open_pull_request(
        credentials,
        branch_name,
        title=f"RankPilot AI: {operation} update",
        body=(
            f"Automated SEO change proposed by RankPilot AI for `{file_path}`.\n\n"
            f"Operation: `{operation}`\nNew value: `{new_value}`\n\n"
            "Review the diff and merge to ship this change — RankPilot AI does not merge "
            "or deploy on custom-code sites."
        ),
    )
    return {
        "pr_number": pull_request["number"],
        "pr_url": pull_request["html_url"],
        "branch": branch_name,
        "file_path": file_path,
    }


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
    # file_path defaults to target_ref's for the plain-HTML/literal case;
    # a data-entry resolution (Next.js App Router) commits to a
    # different file than the one find_target() originally returned.
    file_path = apply_result.get("file_path", target_ref["file_path"])
    response = safe_request(
        httpx.get,
        f"{_repo_api_base(credentials)}/contents/{file_path}",
        headers=credentials.headers,
        params={"ref": branch},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        return False, {"error": f"Could not re-fetch {file_path} on branch {branch}"}

    content = base64.b64decode(response.json()["content"]).decode("utf-8")
    if _is_tsx_source(target_ref["file_path"]):
        resolved = _resolve_tsx_target(credentials, target_ref, operation)
        actual = _extract_tsx_value({**resolved, "content": content})
    else:
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
