"""Settings the Super Admin may change at runtime (whitelist; each validated, confirmed and audited).

Prices here control what RankPilot DISPLAYS and VALIDATES for new checkouts. What a customer is actually
charged is the price configured on the Lemon Squeezy variant, which must be changed there too. Existing
subscriptions always keep the price stored on them when they were bought."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.admin.audit import record_admin_action
from app.config import get_settings
from app.models.admin_setting import AdminSetting
from app.models.user import User


class SettingError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


def _int_range(lo: int, hi: int) -> Callable[[Any], int]:
    def check(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            raise SettingError("invalid_value", f"Must be a whole number between {lo} and {hi}.")
        return value
    return check


def _float_range(lo: float, hi: float) -> Callable[[Any], float]:
    def check(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= float(value) <= hi:
            raise SettingError("invalid_value", f"Must be a number between {lo} and {hi}.")
        return float(value)
    return check


def _one_of(*allowed: str) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        if value not in allowed:
            raise SettingError("invalid_value", f"Must be one of: {', '.join(allowed)}.")
        return value
    return check


@dataclass(frozen=True)
class Spec:
    label: str
    env_attr: str
    validate: Callable[[Any], Any]
    description: str
    sensitive_change: bool = False  # requires an explicit confirmation flag


SPECS: dict[str, Spec] = {
    "price_monthly_cents": Spec("Monthly price (cents)", "price_monthly_cents", _int_range(100, 1_000_000),
                                "Displayed and validated for NEW checkouts. Also change the Lemon Squeezy variant's price.", True),
    "price_annual_cents": Spec("Annual price (cents)", "price_annual_cents", _int_range(100, 10_000_000),
                               "Displayed and validated for NEW checkouts. Also change the Lemon Squeezy variant's price.", True),
    "trial_days": Spec("Free trial length (days)", "trial_days", _int_range(0, 30),
                       "Shown to buyers. The trial itself is configured on the Lemon Squeezy variant; existing trials are unchanged.", True),
    "billing_grace_days": Spec("Payment grace period (days)", "billing_grace_days", _int_range(0, 30),
                               "How long a past-due project keeps access. Applies to payment failures from now on."),
    "billing_enforcement": Spec("Billing enforcement", "billing_enforcement", _one_of("off", "log", "enforce"),
                                "off: nothing gated. log: record decisions. enforce: paid features need a subscription.", True),
    "ai_cost_warning_daily_usd": Spec("AI cost warning (USD / day)", "ai_global_daily_budget_usd", _float_range(0, 100000),
                                      "The AI usage page flags days above this estimated spend."),
    "webhook_failure_warning_count": Spec("Webhook failure warning (count)", "billing_webhook_failure_warning", _int_range(1, 1000),
                                          "System health warns when this many billing events are failed."),
}


def _env_default(spec: Spec) -> Any:
    settings = get_settings()
    if hasattr(settings, spec.env_attr):
        return getattr(settings, spec.env_attr)
    return {"billing_webhook_failure_warning": 5}[spec.env_attr]


def get_value(db: Session, key: str) -> Any:
    spec = SPECS[key]
    row = db.query(AdminSetting).filter(AdminSetting.key == key).one_or_none()
    return row.value_json["value"] if row is not None else _env_default(spec)


def all_settings(db: Session) -> list[dict]:
    rows = {r.key: r for r in db.query(AdminSetting).all()}
    out = []
    for key, spec in SPECS.items():
        row = rows.get(key)
        out.append({
            "key": key, "label": spec.label, "description": spec.description, "sensitive": spec.sensitive_change,
            "value": row.value_json["value"] if row is not None else _env_default(spec),
            "default": _env_default(spec), "source": "admin override" if row is not None else "environment",
            "updated_at": row.updated_at.isoformat() if row is not None and row.updated_at else None,
        })
    return out


def set_value(db: Session, admin: User, key: str, value: Any, *, reason: str, confirm: bool) -> dict:
    spec = SPECS.get(key)
    if spec is None:
        raise SettingError("unknown_setting", "That setting cannot be changed here.", 404)
    if not reason or not reason.strip():
        raise SettingError("reason_required", "A reason is required.")
    if spec.sensitive_change and not confirm:
        raise SettingError("confirmation_required", "This change affects billing. Confirm it explicitly.")
    clean = spec.validate(value)
    row = db.query(AdminSetting).filter(AdminSetting.key == key).one_or_none()
    before = row.value_json["value"] if row is not None else _env_default(spec)
    if row is None:
        row = AdminSetting(key=key, value_json={"value": clean}, updated_by=admin.id)
        db.add(row)
    else:
        row.value_json, row.updated_by = {"value": clean}, admin.id
    record_admin_action(db, admin, action="setting.update", resource_type="setting", resource_id=key,
                        reason=reason.strip(), before={"value": before}, after={"value": clean})
    db.flush()
    return {"key": key, "value": clean, "previous": before}


def reset_value(db: Session, admin: User, key: str, *, reason: str) -> dict:
    spec = SPECS.get(key)
    if spec is None:
        raise SettingError("unknown_setting", "That setting cannot be changed here.", 404)
    if not reason or not reason.strip():
        raise SettingError("reason_required", "A reason is required.")
    row = db.query(AdminSetting).filter(AdminSetting.key == key).one_or_none()
    if row is not None:
        before = row.value_json["value"]
        db.delete(row)
        record_admin_action(db, admin, action="setting.reset", resource_type="setting", resource_id=key,
                            reason=reason.strip(), before={"value": before}, after={"value": _env_default(spec)})
        db.flush()
    return {"key": key, "value": _env_default(spec)}
