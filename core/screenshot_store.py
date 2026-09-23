from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger("core.screenshot_store")


class ScreenshotStore:
    ERROR_SCREENSHOT_PREFIX = "blocks/"
    ERROR_SCREENSHOT_LIFECYCLE_RULE_ID = "expire-error-screenshots-blocks"

    def __init__(self):
        # We use internal hostname for upload (from worker to minio container)
        # but the external/LAN URL base for the frontend to access it.
        self.endpoint = os.getenv("S3_ENDPOINT", "http://minio:9000")
        self.access_key = os.getenv("S3_ACCESS_KEY", "minioadmin")
        self.secret_key = os.getenv("S3_SECRET_KEY", "minioadmin")
        self.bucket = os.getenv("S3_BUCKET", "screenshots")
        self.public_url_base = os.getenv("S3_PUBLIC_URL_BASE")
        self.error_screenshot_retention_days = int(
            (os.getenv("ERROR_SCREENSHOT_RETENTION_DAYS") or "14").strip() or "14"
        )
        
        try:
            self.s3 = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                config=Config(signature_version="s3v4"),
                region_name="us-east-1",
            )
            self._ensure_bucket()
            self._ensure_error_screenshot_lifecycle()
            self._cleanup_expired_error_screenshots()
        except Exception as exc:
            logger.error("No se pudo inicializar S3 client: %s", exc)
            self.s3 = None

    def _ensure_bucket(self):
        if not self.s3:
            return
        try:
            self.s3.head_bucket(Bucket=self.bucket)
        except ClientError:
            try:
                self.s3.create_bucket(Bucket=self.bucket)
                # Public read policy for LAN access
                policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"AWS": ["*"]},
                            "Action": ["s3:GetObject"],
                            "Resource": [f"arn:aws:s3:::{self.bucket}/*"]
                        }
                    ]
                }
                self.s3.put_bucket_policy(Bucket=self.bucket, Policy=json.dumps(policy))
                logger.info("Bucket '%s' creado con politica de lectura publica.", self.bucket)
            except Exception as e:
                logger.error("Fallo al crear bucket o establecer politica: %s", e)

    def _ensure_error_screenshot_lifecycle(self) -> None:
        if not self.s3:
            return
        days = int(self.error_screenshot_retention_days or 0)
        if days <= 0:
            logger.info("Retencion de screenshots de error desactivada (ERROR_SCREENSHOT_RETENTION_DAYS=%s).", days)
            return

        existing_rules: list[dict] = []
        try:
            lifecycle = self.s3.get_bucket_lifecycle_configuration(Bucket=self.bucket)
            existing_rules = [
                rule
                for rule in lifecycle.get("Rules", [])
                if rule.get("ID") != self.ERROR_SCREENSHOT_LIFECYCLE_RULE_ID
            ]
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code not in {"NoSuchLifecycleConfiguration", "NoSuchLifecycleConfigurationError"}:
                logger.warning("No se pudo leer lifecycle de bucket '%s': %s", self.bucket, exc)
        except Exception as exc:
            logger.warning("No se pudo leer lifecycle de bucket '%s': %s", self.bucket, exc)

        existing_rules.append(
            {
                "ID": self.ERROR_SCREENSHOT_LIFECYCLE_RULE_ID,
                "Status": "Enabled",
                "Filter": {"Prefix": self.ERROR_SCREENSHOT_PREFIX},
                "Expiration": {"Days": days},
            }
        )
        try:
            self.s3.put_bucket_lifecycle_configuration(
                Bucket=self.bucket,
                LifecycleConfiguration={"Rules": existing_rules},
            )
            logger.info(
                "Lifecycle aplicado: screenshots de error '%s*' expiran tras %s dias.",
                self.ERROR_SCREENSHOT_PREFIX,
                days,
            )
        except Exception as exc:
            logger.error("Fallo al aplicar lifecycle de screenshots de error: %s", exc)

    def _cleanup_expired_error_screenshots(self) -> None:
        if not self.s3:
            return
        days = int(self.error_screenshot_retention_days or 0)
        if days <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = 0
        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=self.ERROR_SCREENSHOT_PREFIX):
                to_delete: list[dict[str, str]] = []
                for item in page.get("Contents", []):
                    key = str(item.get("Key") or "")
                    last_modified = item.get("LastModified")
                    if not key.startswith(self.ERROR_SCREENSHOT_PREFIX):
                        continue
                    if isinstance(last_modified, datetime):
                        last_modified_utc = (
                            last_modified.astimezone(timezone.utc)
                            if last_modified.tzinfo
                            else last_modified.replace(tzinfo=timezone.utc)
                        )
                        if last_modified_utc < cutoff:
                            to_delete.append({"Key": key})
                for idx in range(0, len(to_delete), 1000):
                    batch = to_delete[idx : idx + 1000]
                    if not batch:
                        continue
                    self.s3.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": batch, "Quiet": True},
                    )
                    deleted += len(batch)
            if deleted:
                logger.info(
                    "Screenshots de error expirados eliminados: %s (prefijo=%s, dias=%s).",
                    deleted,
                    self.ERROR_SCREENSHOT_PREFIX,
                    days,
                )
        except Exception as exc:
            logger.warning("No se pudo limpiar screenshots de error expirados: %s", exc)

    def upload_screenshot(self, site_id: str, resource_id: int, png_bytes: bytes) -> Optional[str]:
        if not self.s3:
            return None
        key = f"{self.ERROR_SCREENSHOT_PREFIX}{site_id}/{resource_id}.png"
        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=png_bytes,
                ContentType="image/png"
            )
            if self.public_url_base:
                return f"{self.public_url_base.rstrip('/')}/{key}"
            # Fallback to internal endpoint (might not work for external users if it's 'minio')
            return f"{self.endpoint.rstrip('/')}/{self.bucket}/{key}"
        except Exception as e:
            logger.error("Fallo al subir screenshot a S3: %s", e)
            return None

    def delete_screenshot(self, site_id: str, resource_id: int) -> bool:
        if not self.s3:
            return False
        key = f"{self.ERROR_SCREENSHOT_PREFIX}{site_id}/{resource_id}.png"
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            logger.error("Fallo al borrar screenshot de S3: %s", e)
            return False

    def get_screenshot_bytes(self, site_id: str, resource_id: int) -> Optional[bytes]:
        if not self.s3:
            return None
        key = f"{self.ERROR_SCREENSHOT_PREFIX}{site_id}/{resource_id}.png"
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            logger.error("Fallo al descargar screenshot de S3: %s", e)
            return None
        except Exception as e:
            logger.error("Fallo al descargar screenshot de S3: %s", e)
            return None



_instance: ScreenshotStore | None = None

def get_screenshot_store() -> ScreenshotStore:
    global _instance
    if _instance is None:
        _instance = ScreenshotStore()
    return _instance
