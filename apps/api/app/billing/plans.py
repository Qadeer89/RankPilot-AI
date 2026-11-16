"""The single source of truth for plans and prices (integer cents)."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.models.billing import BillingInterval


@dataclass(frozen=True)
class Plan:
    interval: BillingInterval
    price_cents: int
    currency: str
    trial_days: int

    @property
    def monthly_equivalent_cents(self) -> int:
        """What this plan contributes to MRR: an annual price divided by 12."""
        return self.price_cents if self.interval == BillingInterval.month else round(self.price_cents / 12)

    @property
    def annual_equivalent_cents(self) -> int:
        return self.price_cents * 12 if self.interval == BillingInterval.month else self.price_cents


def get_plan(interval: BillingInterval) -> Plan:
    settings = get_settings()
    price = settings.price_monthly_cents if interval == BillingInterval.month else settings.price_annual_cents
    return Plan(interval=interval, price_cents=price, currency=settings.billing_currency, trial_days=settings.trial_days)


def all_plans() -> list[Plan]:
    return [get_plan(BillingInterval.month), get_plan(BillingInterval.year)]


def annual_saving_cents() -> int:
    """12 months at the monthly price minus the annual price."""
    return get_plan(BillingInterval.month).price_cents * 12 - get_plan(BillingInterval.year).price_cents
