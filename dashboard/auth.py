from __future__ import annotations


class DashboardAuthStore:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("dashboard/auth.py legacy eliminado. Usa services/auth_rbac.")


class JwtManager:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("JwtManager legacy eliminado. Usa services/auth_rbac.")


def resolve_secret_key() -> str:
    raise RuntimeError("resolve_secret_key legacy eliminado. Usa services/auth_rbac.")
