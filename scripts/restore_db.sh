#!/bin/bash
# ============================================================================
# Workchop API Database Restore
# ============================================================================
# Restores a gzipped pg_dump into the database. Reads DB config from .env
# (POSTGRES_USER, POSTGRES_DB, COMPOSE_PROJECT_NAME). Creates a safety
# backup of the current state before overwriting.
#
# Usage:
#   ./scripts/restore_db.sh ./backups/workchop_backup_20260422_020000.sql.gz
# ============================================================================

set -eo pipefail
# Dumps contain user data: owner-only files and directories.
umask 077

# ---- Load .env ------------------------------------------------------------
# Read single values with grep instead of `source`: the production .env holds passwords and
# JSON, and sourcing it would execute anything shell-special in them.
_env_val() { grep "^${1}=" .env 2>/dev/null | head -1 | cut -d= -f2- || true; }
if [ -f .env ]; then
    COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$(_env_val COMPOSE_PROJECT_NAME)}"
    POSTGRES_USER="${POSTGRES_USER:-$(_env_val POSTGRES_USER)}"
    POSTGRES_DB="${POSTGRES_DB:-$(_env_val POSTGRES_DB)}"
fi

# ---- Configuration --------------------------------------------------------
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-workchop}"
DB_CONTAINER="${DB_CONTAINER:-${COMPOSE_PROJECT_NAME}_db}"
API_CONTAINER="${API_CONTAINER:-${COMPOSE_PROJECT_NAME}_api}"
WORKER_CONTAINER="${WORKER_CONTAINER:-${COMPOSE_PROJECT_NAME}_worker}"
BEAT_CONTAINER="${BEAT_CONTAINER:-${COMPOSE_PROJECT_NAME}_beat}"
DB_USER="${POSTGRES_USER:-}"
DB_NAME="${POSTGRES_DB:-}"

# ---- Colors ---------------------------------------------------------------
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[info] $1${NC}"; }
log_success() { echo -e "${GREEN}[ok]   $1${NC}"; }
log_warning() { echo -e "${YELLOW}[warn] $1${NC}"; }
log_error()   { echo -e "${RED}[err]  $1${NC}"; }

# ---- Validation -----------------------------------------------------------
if [ -z "${DB_USER}" ] || [ -z "${DB_NAME}" ]; then
    log_error "POSTGRES_USER and POSTGRES_DB must be set in .env"
    exit 1
fi

if [ -z "${1:-}" ]; then
    echo ""
    log_error "Usage: ./scripts/restore_db.sh <backup_file.sql.gz>"
    echo ""
    log_info "Available backups:"
    if ls ./backups/workchop_backup_*.sql.gz 1>/dev/null 2>&1; then
        ls -lh ./backups/workchop_backup_*.sql.gz | awk '{print "  " $9 " (" $5 ")"}'
    else
        echo "  No backups found in ./backups/"
    fi
    echo ""
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    log_error "Backup file not found: $BACKUP_FILE"
    exit 1
fi

# ---- Confirmation ---------------------------------------------------------
echo ""
echo "============================================"
echo "  Workchop API Database Restore"
echo "============================================"
echo ""
log_warning "This will OVERWRITE the current database."
log_warning "All existing data will be PERMANENTLY DELETED."
echo ""
log_info "Database:    ${DB_NAME}"
log_info "Container:   ${DB_CONTAINER}"
log_info "Backup file: ${BACKUP_FILE}"
echo ""
read -rp "Type 'yes' to proceed: " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    log_error "Restore cancelled"
    exit 0
fi

# ---- Pre-restore safety backup -------------------------------------------
echo ""
log_info "Creating safety backup of current database..."
mkdir -p ./backups && chmod 700 ./backups
SAFETY_BACKUP="./backups/pre_restore_backup_$(date +%Y%m%d_%H%M%S).sql.gz"
# No `-t` here: a pseudo-TTY rewrites \n to \r\n and silently corrupts a piped dump.
if ! docker exec "${DB_CONTAINER}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" | gzip > "${SAFETY_BACKUP}" \
        || [ "$(gzip -dc "${SAFETY_BACKUP}" | wc -c)" -lt 1000 ]; then
    rm -f "${SAFETY_BACKUP}"
    log_error "Safety backup failed or is empty; refusing to overwrite the database."
    exit 1
fi
log_success "Safety backup created: ${SAFETY_BACKUP}"

# ---- Restore --------------------------------------------------------------
echo ""
log_info "Starting restore..."

if ! docker ps --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
    log_error "Container ${DB_CONTAINER} is not running"
    exit 1
fi

TEMP_FILE="$(mktemp "${TMPDIR:-/tmp}/workchop_restore.XXXXXX")"   # owner-only (umask 077), removed on exit
trap 'rm -f "$TEMP_FILE"' EXIT
if [[ "$BACKUP_FILE" == *.gz ]]; then
    log_info "Decompressing backup..."
    gunzip -c "$BACKUP_FILE" > "$TEMP_FILE"
else
    cp "$BACKUP_FILE" "$TEMP_FILE"
fi

# Quiesce writers first: the API, the worker and beat all hold DB connections and beat/worker
# can write (withdrawal reconcile, auto-confirm) in the middle of a restore otherwise.
log_info "Stopping api / worker / beat for the restore..."
for c in "${API_CONTAINER}" "${WORKER_CONTAINER}" "${BEAT_CONTAINER}"; do
    docker ps -a --format '{{.Names}}' | grep -q "^${c}$" && docker stop "${c}" >/dev/null
done

log_info "Terminating existing database connections..."
docker exec -t "${DB_CONTAINER}" psql -U "${DB_USER}" -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid();" \
    >/dev/null 2>&1 || true

log_info "Recreating database..."
docker exec -t "${DB_CONTAINER}" psql -U "${DB_USER}" -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME};"
docker exec -t "${DB_CONTAINER}" psql -U "${DB_USER}" -d postgres -c "CREATE DATABASE ${DB_NAME};"

log_info "Restoring data..."
# The dump contains `CREATE EXTENSION postgis`; the postgis image provides it. Errors must stop
# the restore and be visible: a half-restored database is worse than a failed restore.
if ! docker exec -i "${DB_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" \
        -v ON_ERROR_STOP=1 --single-transaction -q < "$TEMP_FILE" >/dev/null; then
    log_error "Restore FAILED and was rolled back (database ${DB_NAME} is empty)."
    log_error "Your data is in the safety backup: ${SAFETY_BACKUP}"
    exit 1
fi

if [[ "$BACKUP_FILE" == *.gz ]]; then
    rm -f "$TEMP_FILE"
fi

log_success "Database restored"

# ---- Post-restore service restarts ---------------------------------------
echo ""
log_info "Restarting application containers..."
if docker ps -a --format '{{.Names}}' | grep -q "^${API_CONTAINER}$"; then
    docker restart "${API_CONTAINER}" >/dev/null 2>&1 \
        && log_success "Restarted ${API_CONTAINER}" \
        || log_warning "Failed to restart ${API_CONTAINER}"
fi
for c in "${WORKER_CONTAINER}" "${BEAT_CONTAINER}"; do
    if docker ps -a --format '{{.Names}}' | grep -q "^${c}$"; then
        docker restart "${c}" >/dev/null 2>&1 \
            && log_success "Restarted ${c}" \
            || log_warning "Failed to restart ${c}"
    fi
done

# ---- Summary --------------------------------------------------------------
echo ""
echo "============================================"
log_success "Restore complete"
echo "  Database:        ${DB_NAME}"
echo "  Restored from:   ${BACKUP_FILE}"
echo "  Safety backup:   ${SAFETY_BACKUP}"
echo "============================================"
echo ""
log_warning "Verify the application is working correctly before resuming traffic."
log_warning "The restored data is at the schema version of the BACKUP. If the running image expects a"
log_warning "newer schema, run:  docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head"
echo ""
