"""
Optional S3 persistence for the SQLite database.

Lifecycle:
  - App startup  → download_if_missing(): if no local DB exists, pull from S3.
  - Before deploy → admin clicks "Backup" in the UI → upload() pushes current DB to S3.

On the next Streamlit Cloud deploy the container starts fresh, download_if_missing()
runs, finds the file in S3, and the data is restored.

Configuration — add these to `.streamlit/secrets.toml` locally or Streamlit Cloud
Secrets (Settings → Secrets); `app.py` copies them into the process environment
for boto3:

  AWS_ACCESS_KEY_ID     = "..."
  AWS_SECRET_ACCESS_KEY = "..."
  AWS_REGION            = "us-east-1"   # optional, default us-east-1
  S3_BUCKET             = "my-bucket"
  S3_DB_KEY             = "tennis/tennis.db"   # optional, default shown

If none of these are set the functions silently no-op, so local development
works without any S3 configuration.
"""
from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)


def _config() -> dict | None:
    """Return S3 config dict, or None if not configured."""
    key_id = os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
    bucket = os.environ.get("S3_BUCKET")
    if not all([key_id, secret, bucket]):
        return None
    return {
        "aws_access_key_id": key_id,
        "aws_secret_access_key": secret,
        "region_name": os.environ.get("AWS_REGION", "us-east-1"),
        "bucket": bucket,
        "key": os.environ.get("S3_DB_KEY", "tennis/tennis.db"),
    }


def _client(cfg: dict):
    import boto3
    kwargs = dict(
        aws_access_key_id=cfg["aws_access_key_id"],
        aws_secret_access_key=cfg["aws_secret_access_key"],
        region_name=cfg["region_name"],
    )
    # Cloudflare R2 (or any S3-compatible service) needs a custom endpoint
    endpoint = os.environ.get("R2_ENDPOINT_URL") or os.environ.get("S3_ENDPOINT_URL")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client("s3", **kwargs)


def is_configured() -> bool:
    return _config() is not None


def download_if_missing(db_path: str) -> bool:
    """
    If db_path doesn't exist locally, try to download it from S3.
    Called once at startup. Returns True if a file was downloaded.
    """
    if os.path.exists(db_path):
        return False
    cfg = _config()
    if not cfg:
        return False
    try:
        c = _client(cfg)
        c.download_file(cfg["bucket"], cfg["key"], db_path)
        logger.info("s3_sync: restored DB from s3://%s/%s", cfg["bucket"], cfg["key"])
        return True
    except Exception as e:
        # 404 = first deploy, no backup in S3 yet — that's expected
        logger.debug("s3_sync: no backup found in S3 (%s)", e)
        return False


def upload(db_path: str) -> tuple[bool, str]:
    """
    Upload db_path to S3. Returns (success, message).
    Called explicitly by the admin before deploying.
    """
    cfg = _config()
    if not cfg:
        return False, "S3 no está configurado. Añade las credenciales en los Secrets de Streamlit Cloud."
    if not os.path.exists(db_path):
        return False, "No se encontró la base de datos local."
    try:
        c = _client(cfg)
        c.upload_file(db_path, cfg["bucket"], cfg["key"])
        logger.info("s3_sync: backed up DB to s3://%s/%s", cfg["bucket"], cfg["key"])
        return True, f"Copia guardada en s3://{cfg['bucket']}/{cfg['key']}"
    except Exception as e:
        logger.warning("s3_sync: upload failed (%s)", e)
        return False, f"Error al subir a S3: {e}"
