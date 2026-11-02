#!/usr/bin/env bash
# RP13-019: prove the Alembic migration chain alone -- with no manual
# schema massaging -- produces a schema the full test suite actually
# passes against. Run this after adding/editing a migration, and before
# any release.
#
# Usage: ./scripts/check_clean_install.sh
# Requires: something able to CREATE/DROP DATABASE -- the app's own
# RANKPILOT_DATABASE_URL role usually can't. Set ADMIN_PSQL to however
# this host runs admin psql commands (default: "sudo -u postgres psql",
# matching this project's dev/CI setup); the app role is still what
# actually runs the migration and test suite against the scratch DB.

set -euo pipefail
cd "$(dirname "$0")/.."

SCRATCH_DB="rankpilot_clean_install_test"
BASE_URL="${RANKPILOT_DATABASE_URL:-postgresql+psycopg2://rankpilot:rankpilot_dev@localhost:5432/rankpilot}"
SCRATCH_URL="${BASE_URL%/*}/${SCRATCH_DB}"
ADMIN_PSQL="${ADMIN_PSQL:-sudo -u postgres psql}"

echo "==> Checking for model/migration drift (alembic check)"
alembic check

echo "==> Creating scratch database ${SCRATCH_DB}"
${ADMIN_PSQL} -c "DROP DATABASE IF EXISTS ${SCRATCH_DB};"
${ADMIN_PSQL} -c "CREATE DATABASE ${SCRATCH_DB} OWNER rankpilot;"

echo "==> Running the full migration chain from empty"
RANKPILOT_DATABASE_URL="${SCRATCH_URL}" alembic upgrade head

echo "==> Running the full test suite against the freshly-migrated schema"
RANKPILOT_DATABASE_URL="${SCRATCH_URL}" python -m pytest -q

echo "==> Dropping scratch database"
${ADMIN_PSQL} -c "DROP DATABASE IF EXISTS ${SCRATCH_DB};"

echo "==> Clean install check passed."
