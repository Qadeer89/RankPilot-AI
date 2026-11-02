"""Shared tenant-scoped resource lookups used by multiple endpoint modules."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.website import Website


def get_website_or_404(db: Session, organization_id: uuid.UUID, website_id: uuid.UUID) -> Website:
    website = (
        db.query(Website)
        .filter(Website.id == website_id, Website.organization_id == organization_id)
        .one_or_none()
    )
    if website is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Website not found")
    return website


def get_organization_or_404(db: Session, organization_id: uuid.UUID) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return organization
