from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import jwt


ROLE_ADMIN = "admin"
ROLE_USER = "user"
VALID_ROLES = {ROLE_ADMIN, ROLE_USER}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_username(value: str) -> str:
    return str(value or "").strip().lower()


def hash_password(password: str, iterations: int = 200_000) -> str:
    password_text = str(password or "")
    if len(password_text) < 4:
        raise ValueError("La contraseña debe tener al menos 4 caracteres.")
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


@dataclass(frozen=True)
class AuthUser:
    id: int
    username: str
    role: str
    active: bool

    def to_claims(self) -> dict[str, Any]:
        return {
            "sub": str(self.id),
            "username": self.username,
            "role": self.role,
        }


class DashboardAuthStore:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dashboard_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_dashboard_users_role_active
                ON dashboard_users(role, active)
                """
            )

    def get_user_by_username(self, username: str) -> Optional[dict[str, Any]]:
        username_norm = _normalize_username(username)
        if not username_norm:
            return None
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, username, password_hash, role, active, created_at, updated_at
                FROM dashboard_users
                WHERE username = ?
                LIMIT 1
                """,
                (username_norm,),
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[AuthUser]:
        try:
            user_id_int = int(user_id)
        except Exception:
            return None
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, username, role, active
                FROM dashboard_users
                WHERE id = ?
                LIMIT 1
                """,
                (user_id_int,),
            ).fetchone()
        if not row:
            return None
        return AuthUser(
            id=int(row["id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            active=bool(int(row["active"])),
        )

    def list_users(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, username, role, active, created_at, updated_at
                FROM dashboard_users
                ORDER BY username ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def create_user(self, *, username: str, password: str, role: str = ROLE_USER, active: bool = True) -> AuthUser:
        username_norm = _normalize_username(username)
        if not username_norm:
            raise ValueError("username es obligatorio.")
        role_norm = str(role or "").strip().lower()
        if role_norm not in VALID_ROLES:
            raise ValueError("role invalido. Valores permitidos: admin, user.")

        password_hash = hash_password(password)
        now_iso = _utc_now().isoformat()
        with self._conn() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO dashboard_users (username, password_hash, role, active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (username_norm, password_hash, role_norm, 1 if active else 0, now_iso, now_iso),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Ya existe un usuario con username '{username_norm}'.") from exc
            user_id = int(cur.lastrowid)
        return AuthUser(id=user_id, username=username_norm, role=role_norm, active=bool(active))

    def set_password(self, *, username: str, password: str) -> bool:
        username_norm = _normalize_username(username)
        if not username_norm:
            raise ValueError("username es obligatorio.")
        password_hash = hash_password(password)
        now_iso = _utc_now().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE dashboard_users
                SET password_hash = ?, updated_at = ?
                WHERE username = ?
                """,
                (password_hash, now_iso, username_norm),
            )
        return cur.rowcount > 0

    def ensure_bootstrap_admin(self, *, username: str, password: str) -> AuthUser:
        existing = self.get_user_by_username(username)
        if existing:
            role = str(existing["role"])
            active = bool(int(existing["active"]))
            if role != ROLE_ADMIN or not active:
                with self._conn() as conn:
                    conn.execute(
                        """
                        UPDATE dashboard_users
                        SET role = ?, active = 1, updated_at = ?
                        WHERE id = ?
                        """,
                        (ROLE_ADMIN, _utc_now().isoformat(), int(existing["id"])),
                    )
                if password:
                    self.set_password(username=str(existing["username"]), password=password)
            return AuthUser(
                id=int(existing["id"]),
                username=str(existing["username"]),
                role=ROLE_ADMIN,
                active=True,
            )
        return self.create_user(username=username, password=password, role=ROLE_ADMIN, active=True)

    def authenticate(self, username: str, password: str) -> Optional[AuthUser]:
        row = self.get_user_by_username(username)
        if not row:
            return None
        if not bool(int(row["active"])):
            return None
        if not verify_password(str(password or ""), str(row["password_hash"] or "")):
            return None
        return AuthUser(
            id=int(row["id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            active=True,
        )


class JwtManager:
    def __init__(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        issuer: str = "xaloc-dashboard",
        audience: str = "xaloc-dashboard-clients",
        access_token_minutes: int = 480,
    ):
        secret = str(secret_key or "").strip()
        if not secret:
            raise ValueError("SECRET_KEY no puede estar vacio.")
        self.secret_key = secret
        self.algorithm = algorithm
        self.issuer = issuer
        self.audience = audience
        self.access_token_minutes = max(5, int(access_token_minutes))

    def create_access_token(self, user: AuthUser) -> str:
        now = _utc_now()
        payload: dict[str, Any] = {
            **user.to_claims(),
            "iss": self.issuer,
            "aud": self.audience,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=self.access_token_minutes)).timestamp()),
            "jti": secrets.token_hex(16),
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def decode_access_token(self, token: str) -> dict[str, Any]:
        return jwt.decode(
            str(token or ""),
            self.secret_key,
            algorithms=[self.algorithm],
            audience=self.audience,
            issuer=self.issuer,
        )


def resolve_secret_key() -> str:
    configured = (os.getenv("SECRET_KEY") or "").strip()
    if configured:
        return configured
    return secrets.token_urlsafe(48)
