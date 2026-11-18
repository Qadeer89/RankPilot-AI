"""Version labels stored on every snapshot, so a score or issue count is only ever compared like for like.

Bump ANALYSIS_VERSION when rules are added, removed or change meaning; bump SCORING_VERSION when the health-score
formula changes. Old snapshots keep the version they were produced with."""

ANALYSIS_VERSION = "rules-2026.11"
SCORING_VERSION = "health-v1"
