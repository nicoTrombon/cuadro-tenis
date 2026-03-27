#!/usr/bin/env bash
# deploy.sh — Push to GitHub, which triggers a Streamlit Cloud redeploy.
#
# BEFORE running this script:
#   1. Open the running app on Streamlit Cloud
#   2. Log in as admin
#   3. Click "💾 Guardar copia en S3" in the sidebar
#
# Usage:
#   ./deploy.sh                   # push current HEAD
#   ./deploy.sh "commit message"  # commit staged changes first, then push

set -euo pipefail

info()  { echo "  [deploy] $*"; }

# ── 1. Optional: commit staged changes ───────────────────────────────────────
if [[ $# -gt 0 && -n "$1" ]]; then
    if ! git diff --cached --quiet; then
        info "Committing staged changes: \"$1\""
        git commit -m "$1"
    fi
fi

# ── 2. Confirm DB was backed up ───────────────────────────────────────────────
echo ""
echo "  ⚠️  Have you backed up the database from the running app?"
echo "     (Admin sidebar → 💾 Guardar copia en S3)"
echo ""
read -rp "  Continue deploy? [y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    info "Deploy cancelled."
    exit 0
fi

# ── 3. Push to GitHub → triggers Streamlit Cloud redeploy ────────────────────
info "Pushing to GitHub (origin/main) ..."
git push origin main
info "Done. Streamlit Cloud will redeploy automatically."
