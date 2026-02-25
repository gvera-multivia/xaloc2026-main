import os
import sys
import pytest

sys.path.append(os.getcwd())

pytest.importorskip("psycopg")

from core.pg_control_plane_store import PgControlPlaneStore


def test_build_dedup_key() -> None:
    key = PgControlPlaneStore.build_dedup_key(
        organism_id="madrid",
        external_resource_id="123",
        job_type="P2",
    )
    assert key == "madrid:123:P2"


def test_build_batch_group_key() -> None:
    key = PgControlPlaneStore.build_batch_group_key(
        organism_id="base_online",
        job_type="P1",
        cert_profile="default",
        priority=50,
    )
    assert key == "base_online:P1:default:50"
