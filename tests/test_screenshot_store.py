from __future__ import annotations

from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from core.screenshot_store import ScreenshotStore


class _FakePaginator:
    def __init__(self, pages: list[dict]):
        self.pages = pages
        self.calls: list[dict] = []

    def paginate(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.pages)


class _FakeS3:
    def __init__(self, *, lifecycle: dict | None = None, pages: list[dict] | None = None):
        self.lifecycle = lifecycle
        self.paginator = _FakePaginator(pages or [])
        self.put_lifecycle_calls: list[dict] = []
        self.put_objects: list[dict] = []
        self.delete_objects_calls: list[dict] = []

    def head_bucket(self, *, Bucket: str) -> None:
        return None

    def get_bucket_lifecycle_configuration(self, *, Bucket: str) -> dict:
        if self.lifecycle is None:
            raise ClientError(
                {"Error": {"Code": "NoSuchLifecycleConfiguration"}},
                "GetBucketLifecycleConfiguration",
            )
        return self.lifecycle

    def put_bucket_lifecycle_configuration(self, *, Bucket: str, LifecycleConfiguration: dict) -> None:
        self.put_lifecycle_calls.append(LifecycleConfiguration)

    def put_object(self, **kwargs) -> None:
        self.put_objects.append(kwargs)

    def get_paginator(self, name: str) -> _FakePaginator:
        assert name == "list_objects_v2"
        return self.paginator

    def delete_objects(self, **kwargs) -> None:
        self.delete_objects_calls.append(kwargs)


def test_screenshot_store_lifecycle_only_expires_error_blocks(monkeypatch) -> None:
    fake = _FakeS3(
        lifecycle={
            "Rules": [
                {
                    "ID": "keep-other-assets",
                    "Status": "Enabled",
                    "Filter": {"Prefix": "examples/"},
                    "Expiration": {"Days": 365},
                }
            ]
        }
    )
    monkeypatch.setattr("core.screenshot_store.boto3.client", lambda *_, **__: fake)
    monkeypatch.setenv("ERROR_SCREENSHOT_RETENTION_DAYS", "14")

    ScreenshotStore()

    rules = fake.put_lifecycle_calls[-1]["Rules"]
    assert {
        "ID": "keep-other-assets",
        "Status": "Enabled",
        "Filter": {"Prefix": "examples/"},
        "Expiration": {"Days": 365},
    } in rules
    assert {
        "ID": ScreenshotStore.ERROR_SCREENSHOT_LIFECYCLE_RULE_ID,
        "Status": "Enabled",
        "Filter": {"Prefix": "blocks/"},
        "Expiration": {"Days": 14},
    } in rules


def test_screenshot_store_upload_uses_error_blocks_prefix(monkeypatch) -> None:
    fake = _FakeS3()
    monkeypatch.setattr("core.screenshot_store.boto3.client", lambda *_, **__: fake)
    monkeypatch.setenv("S3_PUBLIC_URL_BASE", "http://example.test/screenshots")

    store = ScreenshotStore()
    url = store.upload_screenshot("madrid", 138104, b"png")

    assert fake.put_objects[-1]["Key"] == "blocks/madrid/138104.png"
    assert url == "http://example.test/screenshots/blocks/madrid/138104.png"


def test_screenshot_store_cleanup_deletes_only_expired_error_blocks(monkeypatch) -> None:
    old = datetime.now(timezone.utc) - timedelta(days=15)
    recent = datetime.now(timezone.utc) - timedelta(days=2)
    fake = _FakeS3(
        pages=[
            {
                "Contents": [
                    {"Key": "blocks/madrid/old.png", "LastModified": old},
                    {"Key": "blocks/madrid/recent.png", "LastModified": recent},
                    {"Key": "examples/old-reference.png", "LastModified": old},
                ]
            }
        ]
    )
    monkeypatch.setattr("core.screenshot_store.boto3.client", lambda *_, **__: fake)
    monkeypatch.setenv("ERROR_SCREENSHOT_RETENTION_DAYS", "14")

    ScreenshotStore()

    assert fake.paginator.calls[-1] == {"Bucket": "screenshots", "Prefix": "blocks/"}
    assert fake.delete_objects_calls == [
        {
            "Bucket": "screenshots",
            "Delete": {"Objects": [{"Key": "blocks/madrid/old.png"}], "Quiet": True},
        }
    ]
