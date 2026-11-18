"""Proposal lifecycle for Shopify SEO changes: draft -> approved -> applied (and verified) | failed | rejected.

Only 'approved' proposals are ever sent to the store, the live value is read back afterwards, and the previous value
is kept so the change can be undone."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai import shopify_optimizer
from app.connectors import shopify
from app.connectors.errors import ConnectorError
from app.history import activity
from app.models.history import CollectionSnapshot, ProductSnapshot
from app.models.shopify_proposal import ShopifyProposal
from app.models.website import Website

OPERATION = {"seo_title": "set_title", "meta_description": "set_meta_description"}
TRANSITIONS = {"draft": {"approved", "rejected"}, "approved": {"rejected"}, "applied": {"rolled_back"}, "failed": {"approved"}, "rejected": set()}


class ProposalError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def create_for_product(db: Session, website: Website, external_id: str) -> list[ShopifyProposal]:
    from app.shopify_seo import catalog
    snap = next((r for r in catalog.latest(db, website, ProductSnapshot) if r.external_id == external_id), None)
    if snap is None:
        raise ProposalError("product_not_found", "That product has not been read from the store yet. Sync the catalog first.")
    current = {"seo_title": snap.seo_title, "meta_description": snap.meta_description}
    try:
        draft, quality = shopify_optimizer.propose(db, website, title=snap.title, description=snap.description_excerpt, image_alts=[a for a in snap.image_alts if a], current=current)
    except ValueError as exc:
        raise ProposalError("draft_rejected", f"The AI draft was not used: {exc}") from exc
    rows = []
    for field, value in (("seo_title", draft.seo_title.strip()), ("meta_description", draft.meta_description.strip())):
        if value == (current.get(field) or "").strip():
            continue
        row = ShopifyProposal(website_id=website.id, resource_type="products", external_id=external_id, title=snap.title, field=field,
                              before_value=current.get(field) or "", proposed_value=value, rationale=draft.rationale, status="draft", quality_json=quality)
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def decide(db: Session, website: Website, proposal: ShopifyProposal, new_status: str, user_id=None, edited_value: str | None = None) -> ShopifyProposal:
    if new_status not in TRANSITIONS.get(proposal.status, set()):
        raise ProposalError("invalid_transition", f"A proposal that is '{proposal.status}' cannot become '{new_status}'.")
    if edited_value is not None and new_status == "approved":
        limit = shopify_optimizer.TITLE_MAX if proposal.field == "seo_title" else shopify_optimizer.META_MAX
        value = edited_value.strip()
        if not value or len(value) > limit:
            raise ProposalError("invalid_edit", f"The edited text must be 1-{limit} characters.")
        proposal.proposed_value = value
        proposal.quality_json = {**proposal.quality_json, "edited_by_person": True}
    proposal.status, proposal.decided_by, proposal.decided_at = new_status, user_id, datetime.now(timezone.utc)
    return proposal


def apply(db: Session, website: Website, proposal: ShopifyProposal, credentials: shopify.ShopifyCredentials) -> ShopifyProposal:
    """Send one approved proposal to the store and read the live value back."""
    if proposal.status != "approved":
        raise ProposalError("not_approved", "Only an approved proposal can be applied.")
    if not website.writes_enabled:
        raise ProposalError("writes_disabled", "Changes to this website are switched off in its settings.")
    operation, ref = OPERATION[proposal.field], {"resource_type": proposal.resource_type, "resource_id": int(proposal.external_id)}
    try:
        proposal.before_value = shopify.get_current_value(credentials, ref, operation)
        result = shopify.apply_change(credentials, ref, operation, proposal.proposed_value)
        ok, evidence = shopify.validate_change(credentials, ref, operation, proposal.proposed_value, result)
    except ConnectorError as exc:
        proposal.status, proposal.failure = "failed", str(exc)[:500]
        return proposal
    proposal.status, proposal.applied_at, proposal.verified, proposal.verification_json = "applied", datetime.now(timezone.utc), ok, evidence
    if not ok:
        proposal.failure = "The store accepted the change but the live value did not match when read back."
    activity.record_event(db, website, "implementation", "shopify_seo_applied", f"Shopify {proposal.field.replace('_', ' ')} updated for '{proposal.title}'",
                          detail={"proposal_id": str(proposal.id), "verified": ok})
    return proposal


def rollback(db: Session, website: Website, proposal: ShopifyProposal, credentials: shopify.ShopifyCredentials) -> ShopifyProposal:
    if proposal.status != "applied":
        raise ProposalError("not_applied", "Only an applied change can be rolled back.")
    ref = {"resource_type": proposal.resource_type, "resource_id": int(proposal.external_id)}
    try:
        shopify.rollback(credentials, ref, OPERATION[proposal.field], proposal.before_value or "", {})
    except ConnectorError as exc:
        raise ProposalError("rollback_failed", str(exc)[:300]) from exc
    proposal.status, proposal.verification_json = "rolled_back", {**(proposal.verification_json or {}), "rolled_back": True}
    activity.record_event(db, website, "implementation", "shopify_seo_rolled_back", f"Shopify {proposal.field.replace('_', ' ')} restored for '{proposal.title}'")
    return proposal
