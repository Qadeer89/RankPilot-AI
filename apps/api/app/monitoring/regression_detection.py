"""SEO regression detection (RankPilot AI Phase 7 "Fully Autonomous
SEO Monitoring" -- "detect SEO regressions").

Deterministic, derived entirely from data this crawl already produced
-- no new scoring logic, no AI involvement. Two signals:

- A brand-new critical finding: SEOFinding.first_detected_at ==
  SEOFinding.last_detected_at is only true for a finding touched for
  the very first time by the persist call that just ran (every later
  crawl that re-detects the same finding updates last_detected_at but
  leaves first_detected_at alone -- app/seo_rules/engine.py's
  _persist_findings). A finding that was previously resolved and has
  now reopened is NOT counted here (first_detected_at predates it) --
  that's a real but different signal this module doesn't claim to be.
- A health-score category that dropped by at least
  SCORE_REGRESSION_THRESHOLD points since the previous crawl
  (SiteHealthScore is already one row per crawl -- app/opportunities/
  health_score.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.crawl_job import CrawlJob
from app.models.seo_finding import FindingSeverity, FindingStatus, SEOFinding
from app.models.website import Website
from app.opportunities.health_score import get_score_history

# A deliberate, documented judgment call (like PENALTY_SCALE in
# health_score.py): a double-digit point drop in one crawl is a real
# regression worth flagging, not routine noise.
SCORE_REGRESSION_THRESHOLD = 10.0

_SCORE_CATEGORIES = (
    "overall_score",
    "technical_score",
    "on_page_score",
    "content_score",
    "performance_score",
)


@dataclass(frozen=True)
class ScoreRegression:
    category: str
    previous_score: float
    current_score: float
    drop: float


@dataclass(frozen=True)
class RegressionSummary:
    new_critical_findings: list[SEOFinding] = field(default_factory=list)
    score_regressions: list[ScoreRegression] = field(default_factory=list)

    @property
    def has_regressions(self) -> bool:
        return bool(self.new_critical_findings or self.score_regressions)


def detect_regressions(db: Session, website: Website, crawl_job: CrawlJob) -> RegressionSummary:
    new_critical_findings = (
        db.query(SEOFinding)
        .filter(
            SEOFinding.website_id == website.id,
            SEOFinding.status == FindingStatus.open,
            SEOFinding.severity == FindingSeverity.critical,
            SEOFinding.first_detected_at == SEOFinding.last_detected_at,
        )
        .all()
    )

    score_regressions: list[ScoreRegression] = []
    scores = get_score_history(db, website, limit=2)
    if len(scores) == 2:
        current, previous = scores[0], scores[1]
        for attr in _SCORE_CATEGORIES:
            prev_val = getattr(previous, attr)
            curr_val = getattr(current, attr)
            if prev_val is None or curr_val is None:
                continue
            drop = prev_val - curr_val
            if drop >= SCORE_REGRESSION_THRESHOLD:
                score_regressions.append(
                    ScoreRegression(category=attr, previous_score=prev_val, current_score=curr_val, drop=drop)
                )

    return RegressionSummary(new_critical_findings=new_critical_findings, score_regressions=score_regressions)
