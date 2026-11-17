"""AI Search Content Readiness: a transparent checklist about how clear, structured and supported a page's
content is. It is NOT a visibility score. It does not predict or guarantee citation by any AI product, and
Search Console queries are Google Search data, not ChatGPT/Gemini prompts."""

from __future__ import annotations

import re

from app.ai_search.answer_analysis import ANSWERED, PARTIAL, UNKNOWN
from app.ai_search.page_content import PageContent
from app.ai_search.terms import coverage

PASS, WARN, FAIL = "pass", "warn", "fail"
DISCLAIMER = (
    "This checks content quality and structure. It does not measure or guarantee visibility in AI answers; "
    "Search Console queries are Google Search data, not AI prompts. AI-platform visibility: unmeasured."
)
_FIGURES = re.compile(r"\b\d[\d,.]*\s?(?:%|percent|years?|days?|weeks?|months?|hours?|minutes?|\$|usd|pkr|rs\.?)|\bfor example\b|\bfor instance\b|\bsuch as\b|\be\.g\.", re.I)


def assess_readiness(query: str, content: PageContent, answer: dict) -> dict:
    if not content.available:
        return {"label": "unknown", "checks": [], "passed": 0, "total": 0, "disclaimer": DISCLAIMER, "ai_visibility": "unmeasured",
                "reason": content.error or "The page content could not be read."}
    checks: list[dict] = []

    def add(name: str, status: str, evidence: str, advice: str) -> None:
        checks.append({"check": name, "status": status, "evidence": evidence, "advice": advice if status != PASS else ""})

    level = answer["level"]
    add("Direct answer under a matching heading", PASS if level == ANSWERED else WARN if level == PARTIAL else FAIL,
        answer["reason"], "Add a short section whose heading states the question and whose first paragraph answers it plainly.")
    excerpt = answer.get("answer_excerpt")
    add("Concise answer paragraph", PASS if excerpt else FAIL, f"{len(excerpt.split())} words" if excerpt else "no 20-140 word answer paragraph found",
        "Open the section with a 2-4 sentence answer before any detail.")
    descriptive = [h for _, h in content.headings if len(h.split()) >= 2]
    add("Descriptive headings", PASS if len(content.headings) >= 3 and len(descriptive) >= len(content.headings) * 0.6 else WARN if content.headings else FAIL,
        f"{len(content.headings)} headings, {len(descriptive)} descriptive", "Use specific, multi-word headings that name what each section covers.")
    structured = content.list_count + content.table_count
    add("Lists or tables for scannable facts", PASS if structured else WARN, f"{content.list_count} lists, {content.table_count} tables",
        "Where the content is a set of steps, options or comparisons, present it as a list or table.")
    has_figures = bool(_FIGURES.search(content.text))
    add("Examples or specifics", PASS if has_figures else WARN, "figures or examples found" if has_figures else "no figures or worked examples found",
        "Support explanations with a concrete example or accurate specifics from your own practice.")
    add("Sources for claims", PASS if content.external_link_count else WARN, f"{content.external_link_count} outbound links",
        "Where a factual claim comes from a third party, cite it. Do not add sources for claims you cannot support.")
    add("Internal references", PASS if content.internal_link_count >= 3 else WARN, f"{content.internal_link_count} internal links",
        "Link to related pages that give the reader the next step.")
    add("Enough depth", PASS if content.word_count >= 300 else WARN if content.word_count >= 120 else FAIL, f"{content.word_count} words",
        "Cover the topic well enough that a reader needs no second source for the basics.")
    aligned = coverage(query, f"{content.title or ''} {content.meta_description or ''}")
    add("Title and description reflect the topic", PASS if aligned >= 0.5 else WARN, f"{aligned * 100:.0f}% of the query's terms in title/description",
        "Make the title and description state what the page answers.")
    add("Structured data present", PASS if content.schema_types else WARN, ", ".join(content.schema_types) or "none",
        "Only add structured data that truthfully describes the page; it is not needed on every page.")

    passed = sum(1 for c in checks if c["status"] == PASS)
    share = passed / len(checks)
    label = "strong" if share >= 0.8 else "moderate" if share >= 0.5 else "needs_work"
    return {"label": label, "checks": checks, "passed": passed, "total": len(checks), "disclaimer": DISCLAIMER, "ai_visibility": "unmeasured"}
