#!/usr/bin/env bash
# deploy.sh — Back up the database to S3, then push to GitHub.
# Streamlit Cloud automatically redeploys when main is updated.
#
# Usage:
#   ./deploy.sh                   # uses current branch HEAD
#   ./deploy.sh "commit message"  # also commits any staged changes first
#
# Requirements:
#   - AWS CLI configured (or AWS_* env vars set)
#   - git remote 'origin' pointing to GitHub
#   - S3_BUCKET and S3_DB_KEY env vars (or set them below)
#
# You can also source a .env file:
#   set -a; source .env; set +a; ./deploy.sh

set -euo pipefail

# ── Config (override via env vars or edit here) ───────────────────────────────
DB_PATH="${DB_PATH:-tennis.db}"
S3_BUCKET="${S3_BUCKET:-}"
S3_DB_KEY="${S3_DB_KEY:-tennis/tennis.db}"
AWS_REGION="${AWS_REGION:-us-east-1}"

# ── Helpers ───────────────────────────────────────────────────────────────────
info()  { echo "  [deploy] $*"; }
error() { echo "  [deploy] ERROR: $*" >&2; exit 1; }

# ── 1. Optional: commit staged changes ───────────────────────────────────────
if [[ $# -gt 0 && -n "$1" ]]; then
    info "Committing staged changes: \"$1\""
    git diff --cached --quiet || git commit -m "$1"
fi

# ── 2. Back up DB to S3 ───────────────────────────────────────────────────────
if [[ -z "$S3_BUCKET" ]]; then
    info "S3_BUCKET not set — skipping database backup."
    info "Set S3_BUCKET (and optionally S3_DB_KEY, AWS_REGION) to enable backups."
elif [[ ! -f "$DB_PATH" ]]; then
    info "No local database found at '$DB_PATH' — skipping backup."
else
    info "Backing up '$DB_PATH' → s3://$S3_BUCKET/$S3_DB_KEY ..."
    if command -v aws &>/dev/null; then
        aws s3 cp "$DB_PATH" "s3://$S3_BUCKET/$S3_DB_KEY" \
            --region "$AWS_REGION" \
            && info "Database backed up successfully." \
            || error "AWS S3 upload failed. Aborting deploy."
    else
        # Fallback: use Python / boto3 (already a project dependency)
        python3 - <<PYEOF
import boto3, os, sys
cfg = {
    "aws_access_key_id":     os.environ.get("AWS_ACCESS_KEY_ID"),
    "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
    "region_name":           os.environ.get("AWS_REGION", "us-east-1"),
}
bucket = os.environ["S3_BUCKET"]
key    = os.environ.get("S3_DB_KEY", "tennis/tennis.db")
db     = os.environ.get("DB_PATH", "tennis.db")
try:
    boto3.client("s3", **cfg).upload_file(db, bucket, key)
    print(f"  [deploy] Database backed up via boto3.")
except Exception as e:
    print(f"  [deploy] ERROR: boto3 upload failed: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
    fi
fi

# ── 3. Push to GitHub → triggers Streamlit Cloud redeploy ────────────────────
info "Pushing to GitHub (origin/main) ..."
git push origin main
info "Done. Streamlit Cloud will redeploy automatically."
