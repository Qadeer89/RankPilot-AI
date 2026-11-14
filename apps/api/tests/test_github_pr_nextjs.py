"""Next.js App Router support for the GitHub PR connector -- see the
module docstring in app/connectors/github_pr.py. Fixtures mirror a real
pattern seen in production: metadata.title/description computed from a
`${identifier.field}` template or a bare `identifier.field` expression,
where `identifier` is bound via `<array>.find(x => x.slug === "...")`
against an imported, slug-keyed data file.
"""

import base64

import pytest

from app.connectors import github_pr
from app.connectors.errors import UnsupportedOperation

CREDENTIALS = github_pr.GitHubCredentials(
    owner="acme", repo="marketing-site", base_branch="main", access_token="ghp_abc123"
)

PAGE_TSX = """import type { Metadata } from "next";
import { services } from "@/lib/services-data";
import { siteConfig } from "@/lib/site-config";

const service = services.find((s) => s.slug === "ai-agents")!;

export const metadata: Metadata = {
  title: `${service.metaTitle} | ${siteConfig.name}`,
  description: service.metaDescription,
  alternates: {
    canonical: `${siteConfig.url}/${service.slug}`,
  },
};

export default function Page() {
  return <div>{service.title}</div>;
}
"""

PAGE_TSX_PLAIN_LITERAL = """import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About Us",
  description: "Learn more about our team.",
};

export default function Page() {
  return <div>About</div>;
}
"""

PAGE_TSX_LOCAL_CONST = """import type { Metadata } from "next";
import { siteConfig } from "@/lib/site-config";

const title = "GoHighLevel Case Study: Clinic Booking";
const description =
  "A real, live GoHighLevel system built for a physiotherapy clinic.";

export const metadata: Metadata = {
  title: `${title} | ${siteConfig.name}`,
  description,
  openGraph: {
    title: `${title} | ${siteConfig.name}`,
    description,
  },
  twitter: {
    description,
  },
};

export default function Page() {
  return <div>{title}</div>;
}
"""

DATA_FILE_TS = """export type ServiceData = {
  slug: string;
  metaTitle: string;
  metaDescription: string;
};

export const services: ServiceData[] = [
  {
    slug: "n8n-automation",
    metaTitle: "n8n Automation Agency",
    metaDescription: "Old n8n description.",
  },
  {
    slug: "ai-agents",
    metaTitle: "Custom AI Agent Development",
    metaDescription: "Old AI agents description.",
  },
];
"""


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(payload)

    def json(self):
        return self._payload


def _encode(content: str) -> str:
    return base64.b64encode(content.encode("utf-8")).decode("ascii")


def _fake_get_for(paths: dict[str, tuple[str, str]]):
    """`paths` maps a URL suffix to (sha, content)."""

    def fake_get(url, params=None, headers=None, timeout=None):
        for suffix, (sha, content) in paths.items():
            if url.endswith(suffix):
                return _FakeResponse(200, {"sha": sha, "content": _encode(content)})
        return _FakeResponse(404, {})

    return fake_get


# --- find_target: Next.js App Router conventions ---------------------


def test_find_target_tries_app_router_convention_after_static_html_misses(monkeypatch):
    attempted = []

    def fake_get(url, params=None, headers=None, timeout=None):
        attempted.append(url)
        if url.endswith("/contents/app/ai-agents/page.tsx"):
            return _FakeResponse(200, {"sha": "page-sha", "content": _encode(PAGE_TSX)})
        return _FakeResponse(404, {})

    monkeypatch.setattr(github_pr.httpx, "get", fake_get)
    target = github_pr.find_target(CREDENTIALS, "https://example.com/ai-agents")
    assert target == {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": PAGE_TSX}
    assert any(u.endswith("/contents/ai-agents.html") for u in attempted)


# --- plain literal values edited directly in page.tsx -----------------


def test_get_current_value_plain_literal_title():
    title_ref = {"file_path": "app/about/page.tsx", "sha": "sha1", "content": PAGE_TSX_PLAIN_LITERAL}
    assert github_pr.get_current_value(CREDENTIALS, title_ref, "set_title") == "About Us"

    description_ref = {"file_path": "app/about/page.tsx", "sha": "sha1", "content": PAGE_TSX_PLAIN_LITERAL}
    assert github_pr.get_current_value(CREDENTIALS, description_ref, "set_meta_description") == (
        "Learn more about our team."
    )


def test_apply_change_plain_literal_edits_page_tsx_directly(monkeypatch):
    monkeypatch.setattr(github_pr.httpx, "get", lambda *a, **k: _FakeResponse(200, {"object": {"sha": "base-sha"}}))
    monkeypatch.setattr(
        github_pr.httpx,
        "post",
        lambda url, json=None, headers=None, timeout=None: (
            _FakeResponse(201, {"ref": json["ref"]})
            if url.endswith("/git/refs")
            else _FakeResponse(201, {"number": 1, "html_url": "https://github.com/acme/marketing-site/pull/1"})
        ),
    )
    committed = {}

    def fake_put(url, json=None, headers=None, timeout=None):
        committed["content"] = base64.b64decode(json["content"]).decode("utf-8")
        committed["path"] = url.rsplit("/contents/", 1)[1]
        return _FakeResponse(200, {"commit": {"sha": "new-sha"}})

    monkeypatch.setattr(github_pr.httpx, "put", fake_put)

    target_ref = {"file_path": "app/about/page.tsx", "sha": "sha1", "content": PAGE_TSX_PLAIN_LITERAL}
    result = github_pr.apply_change(CREDENTIALS, target_ref, "set_title", "About Our Team")

    assert result["file_path"] == "app/about/page.tsx"
    assert committed["path"] == "app/about/page.tsx"
    assert 'title: "About Our Team"' in committed["content"]
    assert "About Us" not in committed["content"]


# --- templated / bare-expression values resolved via an imported data file ---


def test_get_current_value_resolves_template_literal_title_from_data_file(monkeypatch):
    monkeypatch.setattr(
        github_pr.httpx,
        "get",
        _fake_get_for({"/contents/lib/services-data.ts": ("data-sha", DATA_FILE_TS)}),
    )
    target_ref = {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": PAGE_TSX}
    assert github_pr.get_current_value(CREDENTIALS, target_ref, "set_title") == "Custom AI Agent Development"


def test_get_current_value_resolves_bare_expression_description_from_data_file(monkeypatch):
    monkeypatch.setattr(
        github_pr.httpx,
        "get",
        _fake_get_for({"/contents/lib/services-data.ts": ("data-sha", DATA_FILE_TS)}),
    )
    target_ref = {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": PAGE_TSX}
    assert (
        github_pr.get_current_value(CREDENTIALS, target_ref, "set_meta_description")
        == "Old AI agents description."
    )


def test_apply_change_edits_the_data_file_not_the_page(monkeypatch):
    monkeypatch.setattr(
        github_pr.httpx,
        "get",
        _fake_get_for({"/contents/lib/services-data.ts": ("data-sha", DATA_FILE_TS)}),
    )
    pr_calls = []

    def fake_get_combined(url, params=None, headers=None, timeout=None):
        if url.endswith("/git/ref/heads/main"):
            return _FakeResponse(200, {"object": {"sha": "base-sha"}})
        return _fake_get_for({"/contents/lib/services-data.ts": ("data-sha", DATA_FILE_TS)})(
            url, params=params, headers=headers, timeout=timeout
        )

    monkeypatch.setattr(github_pr.httpx, "get", fake_get_combined)

    def fake_post(url, json=None, headers=None, timeout=None):
        pr_calls.append(url)
        if url.endswith("/git/refs"):
            return _FakeResponse(201, {"ref": json["ref"]})
        return _FakeResponse(201, {"number": 7, "html_url": "https://github.com/acme/marketing-site/pull/7"})

    monkeypatch.setattr(github_pr.httpx, "post", fake_post)

    committed = {}

    def fake_put(url, json=None, headers=None, timeout=None):
        committed["content"] = base64.b64decode(json["content"]).decode("utf-8")
        committed["path"] = url.rsplit("/contents/", 1)[1]
        committed["sha"] = json["sha"]
        return _FakeResponse(200, {"commit": {"sha": "new-sha"}})

    monkeypatch.setattr(github_pr.httpx, "put", fake_put)

    target_ref = {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": PAGE_TSX}
    result = github_pr.apply_change(CREDENTIALS, target_ref, "set_title", "AI Agents That Close Deals")

    assert result["file_path"] == "lib/services-data.ts"
    assert committed["path"] == "lib/services-data.ts"
    assert committed["sha"] == "data-sha"
    assert 'metaTitle: "AI Agents That Close Deals"' in committed["content"]
    # The other entry, and this entry's own description, are untouched.
    assert 'metaTitle: "n8n Automation Agency"' in committed["content"]
    assert 'metaDescription: "Old AI agents description."' in committed["content"]


def test_validate_change_rechecks_the_data_file_after_commit(monkeypatch):
    updated_data_file = DATA_FILE_TS.replace(
        'metaTitle: "Custom AI Agent Development"', 'metaTitle: "AI Agents That Close Deals"'
    )
    monkeypatch.setattr(
        github_pr.httpx,
        "get",
        _fake_get_for({"/contents/lib/services-data.ts": ("data-sha", DATA_FILE_TS)}),
    )
    target_ref = {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": PAGE_TSX}
    # Resolve once (as apply_change would), memoized on target_ref.
    github_pr._resolve_tsx_target(CREDENTIALS, target_ref, "set_title")

    def fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/contents/lib/services-data.ts"):
            return _FakeResponse(200, {"sha": "data-sha-2", "content": _encode(updated_data_file)})
        if "/pulls/" in url:
            return _FakeResponse(200, {"state": "open"})
        if "/status" in url:
            return _FakeResponse(200, {"total_count": 0})
        return _FakeResponse(404, {})

    monkeypatch.setattr(github_pr.httpx, "get", fake_get)

    apply_result = {
        "pr_number": 7,
        "pr_url": "https://github.com/acme/marketing-site/pull/7",
        "branch": "rankpilot/set_title-abc123",
        "file_path": "lib/services-data.ts",
    }
    passed, evidence = github_pr.validate_change(
        CREDENTIALS, target_ref, "set_title", "AI Agents That Close Deals", apply_result
    )
    assert evidence["actual"] == "AI Agents That Close Deals"
    assert passed is True


# --- values resolved from a local `const` in the same file (shorthand
# property / bare template interpolation), not an imported data file ---


def test_get_current_value_resolves_bare_template_title_from_local_const():
    target_ref = {"file_path": "app/case-studies/x/page.tsx", "sha": "sha1", "content": PAGE_TSX_LOCAL_CONST}
    assert github_pr.get_current_value(CREDENTIALS, target_ref, "set_title") == (
        "GoHighLevel Case Study: Clinic Booking"
    )


def test_get_current_value_resolves_shorthand_description_from_local_const():
    target_ref = {"file_path": "app/case-studies/x/page.tsx", "sha": "sha1", "content": PAGE_TSX_LOCAL_CONST}
    assert github_pr.get_current_value(CREDENTIALS, target_ref, "set_meta_description") == (
        "A real, live GoHighLevel system built for a physiotherapy clinic."
    )


def test_apply_change_edits_the_local_const_not_the_shorthand_site(monkeypatch):
    monkeypatch.setattr(github_pr.httpx, "get", lambda *a, **k: _FakeResponse(200, {"object": {"sha": "base-sha"}}))
    monkeypatch.setattr(
        github_pr.httpx,
        "post",
        lambda url, json=None, headers=None, timeout=None: (
            _FakeResponse(201, {"ref": json["ref"]})
            if url.endswith("/git/refs")
            else _FakeResponse(201, {"number": 9, "html_url": "https://github.com/acme/marketing-site/pull/9"})
        ),
    )
    committed = {}

    def fake_put(url, json=None, headers=None, timeout=None):
        committed["content"] = base64.b64decode(json["content"]).decode("utf-8")
        committed["path"] = url.rsplit("/contents/", 1)[1]
        return _FakeResponse(200, {"commit": {"sha": "new-sha"}})

    monkeypatch.setattr(github_pr.httpx, "put", fake_put)

    target_ref = {"file_path": "app/case-studies/x/page.tsx", "sha": "page-sha", "content": PAGE_TSX_LOCAL_CONST}
    result = github_pr.apply_change(CREDENTIALS, target_ref, "set_meta_description", "A brand new description.")

    assert result["file_path"] == "app/case-studies/x/page.tsx"
    assert committed["path"] == "app/case-studies/x/page.tsx"
    assert 'const description =\n  "A brand new description.";' in committed["content"]
    # The shorthand properties that reuse it (openGraph, twitter) are
    # untouched source text -- they pick up the new value automatically
    # at build time since they all reference the same const.
    assert committed["content"].count("description,") == 3
    assert "A real, live GoHighLevel" not in committed["content"]


# --- unresolvable shapes fail clearly, never guessing ------------------


def test_raises_when_template_has_multiple_resolvable_references():
    page = PAGE_TSX.replace(
        'description: service.metaDescription,',
        'description: `${service.metaDescription} - ${other.metaDescription}`,',
    ).replace(
        "const service = services.find",
        'const other = services.find((s) => s.slug === "n8n-automation")!;\nconst service = services.find',
    )
    target_ref = {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": page}
    with pytest.raises(UnsupportedOperation, match="more than one"):
        github_pr.get_current_value(CREDENTIALS, target_ref, "set_meta_description")


def test_raises_when_value_has_no_resolvable_reference():
    # Not a quoted literal, template, or bare `identifier.field` expression --
    # the field-value regex simply doesn't match a function-call expression,
    # so this fails clearly as "field not found" rather than guessing.
    page = PAGE_TSX.replace("service.metaDescription", "computeDescription()")
    target_ref = {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": page}
    with pytest.raises(UnsupportedOperation, match="No `description:` field found"):
        github_pr.get_current_value(CREDENTIALS, target_ref, "set_meta_description")


def test_raises_when_template_expression_is_not_find_bound():
    # A template with a single interpolation that resolves to nothing
    # `.find()`-bound (e.g. a plain module-level constant) has zero
    # resolvable references, same bucket as "no reference at all".
    page = PAGE_TSX.replace(
        "description: service.metaDescription,", "description: `${siteConfig.name} overview`,"
    )
    target_ref = {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": page}
    with pytest.raises(UnsupportedOperation, match="template with no data-file-resolvable"):
        github_pr.get_current_value(CREDENTIALS, target_ref, "set_meta_description")


def test_raises_when_no_metadata_export_found():
    target_ref = {
        "file_path": "app/about/page.tsx",
        "sha": "sha1",
        "content": "export default function Page() { return <div>Hi</div>; }",
    }
    with pytest.raises(UnsupportedOperation, match="metadata"):
        github_pr.get_current_value(CREDENTIALS, target_ref, "set_title")


def test_raises_explains_inherited_layout_metadata_rather_than_a_bare_not_found():
    # Mirrors a real homepage (app/page.tsx with no metadata export of
    # its own, relying entirely on the root layout.tsx's shared
    # default) -- the error must say WHY, not just that nothing was
    # found, and must not attempt to resolve/edit the layout file.
    target_ref = {
        "file_path": "app/page.tsx",
        "sha": "sha1",
        "content": "export default function Home() { return <div>Welcome</div>; }",
    }
    with pytest.raises(UnsupportedOperation, match="inherited from a parent `layout.tsx`"):
        github_pr.get_current_value(CREDENTIALS, target_ref, "set_meta_description")


def test_raises_when_metadata_field_absent():
    target_ref = {
        "file_path": "app/about/page.tsx",
        "sha": "sha1",
        "content": 'export const metadata = { description: "only a description" };',
    }
    with pytest.raises(UnsupportedOperation, match="title"):
        github_pr.get_current_value(CREDENTIALS, target_ref, "set_title")


def test_raises_when_find_binding_not_found_for_identifier():
    # No `.find()` binding for `service` means neither of the title
    # template's two interpolations is data-file-resolvable.
    page = PAGE_TSX.replace(
        'const service = services.find((s) => s.slug === "ai-agents")!;', "const service = getService();"
    )
    target_ref = {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": page}
    with pytest.raises(UnsupportedOperation, match="template with no data-file-resolvable"):
        github_pr.get_current_value(CREDENTIALS, target_ref, "set_title")


def test_raises_when_import_not_found_for_array():
    page = PAGE_TSX.replace('import { services } from "@/lib/services-data";\n', "")
    target_ref = {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": page}
    with pytest.raises(UnsupportedOperation, match="imported from"):
        github_pr.get_current_value(CREDENTIALS, target_ref, "set_title")


def test_raises_when_non_alias_import_path():
    page = PAGE_TSX.replace('"@/lib/services-data"', '"../../shared/services-data"')
    target_ref = {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": page}
    with pytest.raises(UnsupportedOperation, match="alias"):
        github_pr.get_current_value(CREDENTIALS, target_ref, "set_title")


def test_raises_when_data_file_not_found(monkeypatch):
    monkeypatch.setattr(github_pr.httpx, "get", lambda *a, **k: _FakeResponse(404, {}))
    target_ref = {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": PAGE_TSX}
    with pytest.raises(UnsupportedOperation, match="data file"):
        github_pr.get_current_value(CREDENTIALS, target_ref, "set_title")


def test_raises_when_slug_entry_not_found_in_data_file(monkeypatch):
    data_without_entry = DATA_FILE_TS.replace('slug: "ai-agents",\n    metaTitle: "Custom AI Agent Development",\n    metaDescription: "Old AI agents description.",\n  },\n', "")
    monkeypatch.setattr(
        github_pr.httpx,
        "get",
        _fake_get_for({"/contents/lib/services-data.ts": ("data-sha", data_without_entry)}),
    )
    target_ref = {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": PAGE_TSX}
    with pytest.raises(UnsupportedOperation, match="entry"):
        github_pr.get_current_value(CREDENTIALS, target_ref, "set_title")


def test_set_schema_json_is_not_supported_for_tsx_source():
    target_ref = {"file_path": "app/ai-agents/page.tsx", "sha": "page-sha", "content": PAGE_TSX}
    with pytest.raises(UnsupportedOperation, match="not supported"):
        github_pr.get_current_value(CREDENTIALS, target_ref, "set_schema_json")


# --- static-site/.html behavior is unchanged ---------------------------


def test_static_html_path_is_untouched_by_tsx_logic():
    html = (
        "<html><head><title>Old Title</title>"
        '<meta name="description" content="Old description"></head><body></body></html>'
    )
    target_ref = {"file_path": "about.html", "sha": "sha1", "content": html}
    assert github_pr.get_current_value(CREDENTIALS, target_ref, "set_title") == "Old Title"
