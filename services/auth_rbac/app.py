from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import jwt
import psycopg
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import Response
from psycopg.rows import dict_row

from core.runtime_flags import get_report_pg_dsn

AUTH_COOKIE_NAME = "dashboard_access_token"
AUTH_ROLE_COOKIE_NAME = "dashboard_role"

ROLE_ADMIN = "admin"
ROLE_CONSULTOR = "consultor"
ROLE_COMERCIAL = "comercial"
ROLE_CLIENTE = "cliente"
ROLE_USER = "user"  # compat legado
VALID_ROLES = {ROLE_ADMIN, ROLE_CONSULTOR, ROLE_COMERCIAL, ROLE_CLIENTE, ROLE_USER}

DEFAULT_ROLE_SCOPES: dict[str, set[str]] = {
    ROLE_ADMIN: {"*"},
    ROLE_CONSULTOR: {"jobs:read", "history:read", "incidents:read", "blacklist:read"},
    ROLE_COMERCIAL: {"jobs:read", "jobs:update", "incidents:read", "incidents:update", "blacklist:read"},
    ROLE_CLIENTE: {"jobs:read", "history:read"},
    ROLE_USER: {"jobs:read", "history:read", "incidents:read"},
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_username(value: str) -> str:
    return str(value or "").strip().lower()


def hash_password(password: str, iterations: int = 200_000) -> str:
    password_text = str(password or "")
    if len(password_text) < 4:
        raise ValueError("La password debe tener al menos 4 caracteres.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password_text.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, iter_text, salt_b64, digest_b64 = str(password_hash).split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_text)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
    except Exception:
        return False
    computed = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, iterations)
    return hmac.compare_digest(computed, expected)


def _resolve_secret_key() -> str:
    configured = (os.getenv("SECRET_KEY") or "").strip()
    if configured:
        return configured
    return secrets.token_urlsafe(48)


def _resolve_pg_dsn() -> str:
    dsn = get_report_pg_dsn() or ""
    if not dsn:
        raise RuntimeError("REPORT_PG_DSN/PG_DSN es obligatorio para auth-rbac-service.")
    return dsn


@dataclass(frozen=True)
class AuthUser:
    id: int
    username: str
    role: str
    active: bool

    def to_claims(self, scopes: list[dict[str, Optional[str]]]) -> dict[str, Any]:
        return {"sub": str(self.id), "username": self.username, "role": self.role, "scopes": scopes}


class AuthRbacStore:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._init_schema()

    def _conn(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def _init_schema(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auth_users (
                        id BIGSERIAL PRIMARY KEY,
                        username TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL,
                        active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auth_user_scopes (
                        id BIGSERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                        scope TEXT NOT NULL,
                        organism_id TEXT NULL,
                        client_id TEXT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS ix_auth_user_scopes_user ON auth_user_scopes(user_id)")
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_auth_user_scopes_unique
                    ON auth_user_scopes (
                        user_id, scope, COALESCE(organism_id, ''), COALESCE(client_id, '')
                    )
                    """
                )
            conn.commit()

    def get_user_by_username(self, username: str) -> Optional[dict[str, Any]]:
        username_norm = _normalize_username(username)
        if not username_norm:
            return None
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, password_hash, role, active, created_at, updated_at
                    FROM auth_users WHERE username = %s LIMIT 1
                    """,
                    (username_norm,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[AuthUser]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, username, role, active FROM auth_users WHERE id = %s LIMIT 1", (int(user_id),))
                row = cur.fetchone()
        if not row:
            return None
        return AuthUser(
            id=int(row["id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            active=bool(row["active"]),
        )

    def list_user_scopes(self, user_id: int) -> list[dict[str, Optional[str]]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT scope, organism_id, client_id
                    FROM auth_user_scopes
                    WHERE user_id = %s
                    ORDER BY scope ASC, organism_id ASC, client_id ASC
                    """,
                    (int(user_id),),
                )
                rows = cur.fetchall()
        return [
            {
                "scope": str(row["scope"]),
                "organism_id": str(row["organism_id"]) if row["organism_id"] is not None else None,
                "client_id": str(row["client_id"]) if row["client_id"] is not None else None,
            }
            for row in rows
        ]

    @staticmethod
    def effective_scopes_for_role(*, role: str, user_scopes: list[dict[str, Optional[str]]]) -> list[dict[str, Optional[str]]]:
        role_norm = str(role or "").strip().lower()
        defaults = [{"scope": s, "organism_id": None, "client_id": None} for s in sorted(DEFAULT_ROLE_SCOPES.get(role_norm, set()))]
        merged = defaults + list(user_scopes or [])
        dedup: dict[str, dict[str, Optional[str]]] = {}
        for item in merged:
            key = f"{item.get('scope')}|{item.get('organism_id') or ''}|{item.get('client_id') or ''}"
            dedup[key] = item
        return list(dedup.values())

    def list_users(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, username, role, active, created_at, updated_at
                    FROM auth_users ORDER BY username ASC
                    """
                )
                rows = cur.fetchall()
        items = [dict(r) for r in rows]
        for item in items:
            item["scopes"] = self.effective_scopes_for_role(
                role=str(item["role"]),
                user_scopes=self.list_user_scopes(int(item["id"])),
            )
        return items

    def create_user(self, *, username: str, password: str, role: str = ROLE_USER, active: bool = True) -> AuthUser:
        username_norm = _normalize_username(username)
        if not username_norm:
            raise ValueError("username es obligatorio.")
        role_norm = str(role or "").strip().lower()
        if role_norm not in VALID_ROLES:
            raise ValueError("role invalido.")
        password_hash = hash_password(password)
        now_iso = _utc_now().isoformat()
        with self._conn() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO auth_users (username, password_hash, role, active, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
                        RETURNING id
                        """,
                        (username_norm, password_hash, role_norm, bool(active), now_iso, now_iso),
                    )
                except Exception as exc:
                    raise ValueError(f"Ya existe un usuario con username '{username_norm}'.") from exc
                user_id = int(cur.fetchone()["id"])
            conn.commit()
        return AuthUser(id=user_id, username=username_norm, role=role_norm, active=bool(active))

    def update_user(
        self,
        user_id: int,
        *,
        username: Optional[str] = None,
        role: Optional[str] = None,
        active: Optional[bool] = None,
        password: Optional[str] = None,
    ) -> bool:
        updates: list[str] = []
        params: list[Any] = []
        if username is not None:
            username_norm = _normalize_username(username)
            if not username_norm:
                raise ValueError("username no puede estar vacio.")
            updates.append("username = %s")
            params.append(username_norm)
        if role is not None:
            role_norm = str(role).strip().lower()
            if role_norm not in VALID_ROLES:
                raise ValueError("role invalido.")
            updates.append("role = %s")
            params.append(role_norm)
        if active is not None:
            updates.append("active = %s")
            params.append(bool(active))
        if password is not None:
            updates.append("password_hash = %s")
            params.append(hash_password(password))
        if not updates:
            return False
        updates.append("updated_at = %s::timestamptz")
        params.append(_utc_now().isoformat())
        params.append(int(user_id))
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE auth_users SET {', '.join(updates)} WHERE id = %s", tuple(params))
                updated = cur.rowcount > 0
            conn.commit()
        return updated

    def delete_user(self, user_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM auth_users WHERE id = %s", (int(user_id),))
                deleted = cur.rowcount > 0
            conn.commit()
        return deleted

    def set_password(self, *, username: str, password: str) -> bool:
        username_norm = _normalize_username(username)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth_users
                    SET password_hash = %s, updated_at = %s::timestamptz
                    WHERE username = %s
                    """,
                    (hash_password(password), _utc_now().isoformat(), username_norm),
                )
                ok = cur.rowcount > 0
            conn.commit()
        return ok

    def upsert_scope(self, *, user_id: int, scope: str, organism_id: Optional[str] = None, client_id: Optional[str] = None) -> dict[str, Optional[str]]:
        scope_norm = str(scope or "").strip()
        if not scope_norm:
            raise ValueError("scope es obligatorio.")
        organism_norm = str(organism_id).strip() if organism_id else None
        client_norm = str(client_id).strip() if client_id else None
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO auth_user_scopes (user_id, scope, organism_id, client_id)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, scope, COALESCE(organism_id, ''), COALESCE(client_id, '')) DO NOTHING
                    """,
                    (int(user_id), scope_norm, organism_norm, client_norm),
                )
            conn.commit()
        return {"scope": scope_norm, "organism_id": organism_norm, "client_id": client_norm}

    def delete_scope(self, *, user_id: int, scope: str, organism_id: Optional[str] = None, client_id: Optional[str] = None) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM auth_user_scopes
                    WHERE user_id = %s AND scope = %s
                      AND COALESCE(organism_id, '') = COALESCE(%s, '')
                      AND COALESCE(client_id, '') = COALESCE(%s, '')
                    """,
                    (int(user_id), str(scope or "").strip(), organism_id, client_id),
                )
                deleted = cur.rowcount > 0
            conn.commit()
        return deleted

    def ensure_bootstrap_admin(self, *, username: str, password: str) -> AuthUser:
        existing = self.get_user_by_username(username)
        if existing:
            if str(existing["role"]) != ROLE_ADMIN or not bool(existing["active"]):
                with self._conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE auth_users
                            SET role = %s, active = TRUE, updated_at = %s::timestamptz
                            WHERE id = %s
                            """,
                            (ROLE_ADMIN, _utc_now().isoformat(), int(existing["id"])),
                        )
                    conn.commit()
            if password:
                self.set_password(username=str(existing["username"]), password=password)
            return AuthUser(id=int(existing["id"]), username=str(existing["username"]), role=ROLE_ADMIN, active=True)
        return self.create_user(username=username, password=password, role=ROLE_ADMIN, active=True)

    def authenticate(self, username: str, password: str) -> Optional[AuthUser]:
        row = self.get_user_by_username(username)
        if not row:
            return None
        if not bool(row["active"]):
            return None
        if not verify_password(str(password or ""), str(row["password_hash"] or "")):
            return None
        return AuthUser(id=int(row["id"]), username=str(row["username"]), role=str(row["role"]), active=True)


class JwtManager:
    def __init__(self, *, secret_key: str, algorithm: str = "HS256", issuer: str = "xaloc-dashboard", audience: str = "xaloc-dashboard-clients", access_token_minutes: int = 480):
        secret = str(secret_key or "").strip()
        if not secret:
            raise ValueError("SECRET_KEY no puede estar vacio.")
        self.secret_key = secret
        self.algorithm = algorithm
        self.issuer = issuer
        self.audience = audience
        self.access_token_minutes = max(5, int(access_token_minutes))

    def create_access_token(self, user: AuthUser, scopes: list[dict[str, Optional[str]]]) -> str:
        now = _utc_now()
        payload: dict[str, Any] = {
            **user.to_claims(scopes=scopes),
            "iss": self.issuer,
            "aud": self.audience,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=self.access_token_minutes)).timestamp()),
            "jti": secrets.token_hex(16),
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def decode_access_token(self, token: str) -> dict[str, Any]:
        return jwt.decode(str(token or ""), self.secret_key, algorithms=[self.algorithm], audience=self.audience, issuer=self.issuer)


def _extract_bearer_from_authorization(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _extract_token_from_request(request: Request, authorization: Optional[str]) -> Optional[str]:
    header_token = _extract_bearer_from_authorization(authorization)
    if header_token:
        return header_token
    return request.cookies.get(AUTH_COOKIE_NAME)


app = FastAPI(title="auth-rbac-service", version="0.2.0")
store = AuthRbacStore(dsn=_resolve_pg_dsn())
jwt_manager = JwtManager(
    secret_key=_resolve_secret_key(),
    issuer=(os.getenv("DASHBOARD_JWT_ISSUER") or "xaloc-dashboard").strip() or "xaloc-dashboard",
    audience=(os.getenv("DASHBOARD_JWT_AUDIENCE") or "xaloc-dashboard-clients").strip() or "xaloc-dashboard-clients",
    access_token_minutes=max(5, int((os.getenv("DASHBOARD_TOKEN_EXPIRE_MINUTES") or "480").strip() or "480")),
)
AUTH_COOKIE_SECURE = (os.getenv("DASHBOARD_AUTH_COOKIE_SECURE") or "0").strip().lower() in {"1", "true", "yes", "on"}


def _build_claims_for_user(user: AuthUser) -> dict[str, Any]:
    raw_scopes = store.list_user_scopes(user.id)
    scopes = store.effective_scopes_for_role(role=user.role, user_scopes=raw_scopes)
    return user.to_claims(scopes=scopes)


@app.on_event("startup")
def _startup() -> None:
    bootstrap_admin_user = (os.getenv("DASHBOARD_ADMIN_USERNAME") or "").strip().lower()
    bootstrap_admin_password = (os.getenv("DASHBOARD_ADMIN_PASSWORD") or "").strip()
    if bootstrap_admin_user and bootstrap_admin_password:
        store.ensure_bootstrap_admin(username=bootstrap_admin_user, password=bootstrap_admin_password)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.post("/auth/login")
async def auth_login(payload: dict[str, Any] = Body(...)) -> Response:
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="username y password son obligatorios.")
    user = store.authenticate(username=username, password=password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales invalidas.")
    claims = _build_claims_for_user(user)
    token = jwt_manager.create_access_token(user, claims.get("scopes") or [])
    response = Response(content=json.dumps({"ok": True, "user": claims}), media_type="application/json")
    response.set_cookie(key=AUTH_COOKIE_NAME, value=token, httponly=True, secure=AUTH_COOKIE_SECURE, samesite="lax", max_age=jwt_manager.access_token_minutes * 60, path="/")
    response.set_cookie(key=AUTH_ROLE_COOKIE_NAME, value=user.role, httponly=False, secure=AUTH_COOKIE_SECURE, samesite="lax", max_age=jwt_manager.access_token_minutes * 60, path="/")
    return response


@app.post("/auth/logout")
async def auth_logout() -> Response:
    response = Response(content='{"ok": true}', media_type="application/json")
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    response.delete_cookie(AUTH_ROLE_COOKIE_NAME, path="/")
    return response


def _decode_token_or_401(token: str) -> dict[str, Any]:
    try:
        return jwt_manager.decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


@app.get("/auth/me")
async def auth_me(request: Request, authorization: Optional[str] = Header(None)) -> dict[str, Any]:
    token = _extract_token_from_request(request, authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing auth token")
    payload = _decode_token_or_401(token)
    user = store.get_user_by_id(int(str(payload.get("sub") or "0")))
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return {"authenticated": True, "user": _build_claims_for_user(user)}


@app.post("/auth/introspect")
async def auth_introspect(request: Request, authorization: Optional[str] = Header(None)) -> dict[str, Any]:
    return await auth_me(request=request, authorization=authorization)


async def _require_admin(request: Request, authorization: Optional[str] = Header(None)) -> dict[str, Any]:
    me = await auth_me(request=request, authorization=authorization)
    user = me.get("user") or {}
    if str(user.get("role") or "").strip().lower() != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


@app.get("/auth/users")
async def auth_users_list(_admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    items = store.list_users()
    return {"items": items, "total": len(items)}


@app.post("/auth/users")
async def auth_users_create(payload: dict[str, Any] = Body(...), _admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    user = store.create_user(
        username=str(payload.get("username") or "").strip(),
        password=str(payload.get("password") or ""),
        role=str(payload.get("role") or ROLE_USER).strip().lower(),
        active=bool(payload.get("active", True)),
    )
    claims = _build_claims_for_user(user)
    return {"created": True, "user": claims | {"active": user.active}}


@app.put("/auth/users/{user_id}")
async def auth_users_update(user_id: int, payload: dict[str, Any] = Body(...), _admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    ok = store.update_user(
        user_id=user_id,
        username=payload.get("username"),
        role=payload.get("role"),
        active=payload.get("active"),
        password=payload.get("password"),
    )
    return {"updated": ok}


@app.delete("/auth/users/{user_id}")
async def auth_users_delete(user_id: int, _admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    return {"deleted": store.delete_user(user_id)}


@app.get("/auth/users/{user_id}/scopes")
async def auth_user_scopes_list(user_id: int, _admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    user = store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    scopes = store.effective_scopes_for_role(role=user.role, user_scopes=store.list_user_scopes(user_id))
    return {"items": scopes, "total": len(scopes)}


@app.post("/auth/users/{user_id}/scopes")
async def auth_user_scopes_add(user_id: int, payload: dict[str, Any] = Body(...), _admin: dict[str, Any] = Depends(_require_admin)) -> dict[str, Any]:
    user = store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    item = store.upsert_scope(
        user_id=user_id,
        scope=str(payload.get("scope") or "").strip(),
        organism_id=payload.get("organism_id"),
        client_id=payload.get("client_id"),
    )
    return {"created": True, "scope": item}


@app.delete("/auth/users/{user_id}/scopes")
async def auth_user_scopes_delete(
    user_id: int,
    scope: str,
    organism_id: str | None = None,
    client_id: str | None = None,
    _admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, Any]:
    user = store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"deleted": store.delete_scope(user_id=user_id, scope=scope, organism_id=organism_id, client_id=client_id)}
