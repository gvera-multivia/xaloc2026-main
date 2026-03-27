from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Body, Depends, Request, Response, WebSocket, WebSocketDisconnect

import dashboard_api as api
from core.redis_client import get_redis_client

router = APIRouter()


@router.post("/api/auth/login")
async def api_auth_login(request: Request, payload: dict[str, Any] = Body(...)) -> Response:
    return await api._proxy_auth_service(method="POST", path="/auth/login", request=request, payload=payload)


@router.post("/api/auth/register")
async def api_auth_register(request: Request, payload: dict[str, Any] = Body(...)) -> Response:
    return await api._proxy_auth_service(method="POST", path="/auth/register", request=request, payload=payload)


@router.get("/api/auth/me")
async def api_auth_me(request: Request, _user: dict[str, Any] = Depends(api.require_user)) -> Response:
    return await api._proxy_auth_service(method="GET", path="/auth/me", request=request)


@router.post("/api/auth/logout")
async def api_auth_logout(request: Request) -> Response:
    return await api._proxy_auth_service(method="POST", path="/auth/logout", request=request)


@router.get("/api/auth/users")
async def api_auth_list_users(request: Request, _admin: dict[str, Any] = Depends(api.require_admin)) -> Response:
    return await api._proxy_auth_service(method="GET", path="/auth/users", request=request)


@router.post("/api/auth/users")
async def api_auth_create_user(
    request: Request,
    payload: dict[str, Any] = Body(...),
    _admin: dict[str, Any] = Depends(api.require_admin),
) -> Response:
    return await api._proxy_auth_service(method="POST", path="/auth/users", request=request, payload=payload)


@router.put("/api/auth/users/{user_id}")
async def api_auth_update_user(
    request: Request,
    user_id: int,
    payload: dict[str, Any] = Body(...),
    _admin: dict[str, Any] = Depends(api.require_admin),
) -> Response:
    return await api._proxy_auth_service(method="PUT", path=f"/auth/users/{int(user_id)}", request=request, payload=payload)


@router.delete("/api/auth/users/{user_id}")
async def api_auth_delete_user(
    request: Request,
    user_id: int,
    _admin: dict[str, Any] = Depends(api.require_admin),
) -> Response:
    return await api._proxy_auth_service(method="DELETE", path=f"/auth/users/{int(user_id)}", request=request)


@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    api.logger.error(">>> WEBSOCKET HANDSHAKE REACHED ROUTE")
    if not api.ENABLE_WS_REALTIME:
        await websocket.close(code=1008, reason="Realtime disabled")
        return

    candidate_tokens = api._extract_tokens_from_websocket(websocket)
    query_token = (websocket.query_params.get("token") or "").strip()
    header_token = (api._extract_bearer_from_authorization(websocket.headers.get("authorization")) or "").strip()
    cookie_token = (websocket.cookies.get(api.AUTH_COOKIE_NAME) or "").strip()
    api.logger.warning(
        "WS auth candidates query=%s header=%s cookie=%s query_exp=%s header_exp=%s cookie_exp=%s",
        bool(query_token),
        bool(header_token),
        bool(cookie_token),
        api._token_exp_unverified(query_token) if query_token else None,
        api._token_exp_unverified(header_token) if header_token else None,
        api._token_exp_unverified(cookie_token) if cookie_token else None,
    )
    if not candidate_tokens:
        api._WS_DEBUG_STATS["rejected_missing_token"] += 1
        await websocket.close(code=4401, reason="Missing auth token")
        return

    authenticated = False
    for token in candidate_tokens:
        try:
            await api._auth_introspect(token)
            authenticated = True
            break
        except Exception:
            continue

    if not authenticated:
        api._WS_DEBUG_STATS["rejected_invalid_token"] += 1
        await websocket.close(code=4401, reason="Invalid auth token")
        return

    redis = get_redis_client()
    if not redis:
        api._WS_DEBUG_STATS["rejected_redis_unavailable"] += 1
        await websocket.close(code=1013, reason="Realtime backend unavailable")
        return

    pubsub = None
    try:
        pubsub = redis.pubsub()
        await pubsub.subscribe("channel:ui_updates")
    except Exception as exc:
        api.logger.warning("WebSocket realtime disabled: Redis unavailable (%s)", exc)
        if pubsub is not None:
            try:
                await pubsub.close()
            except Exception:
                pass
        await websocket.close(code=1013, reason="Realtime backend unavailable")
        return

    await websocket.accept()
    api._WS_ACTIVE_CONNECTIONS += 1
    api._WS_DEBUG_STATS["accepted"] += 1

    async def _forward_pubsub_to_ws() -> None:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            raw_data = message.get("data")
            if isinstance(raw_data, bytes):
                text_data = raw_data.decode("utf-8", errors="replace")
            elif isinstance(raw_data, str):
                text_data = raw_data
            else:
                text_data = json.dumps(raw_data, ensure_ascii=False)
            await websocket.send_text(text_data)

    async def _watch_client_disconnect() -> None:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break

    sender_task = asyncio.create_task(_forward_pubsub_to_ws())
    watcher_task = asyncio.create_task(_watch_client_disconnect())

    try:
        done, pending = await asyncio.wait(
            {sender_task, watcher_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                api.logger.error(f"WebSocket task error: {exc}")
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        api.logger.error(f"WebSocket error: {exc}")
    finally:
        api._WS_ACTIVE_CONNECTIONS = max(0, api._WS_ACTIVE_CONNECTIONS - 1)
        if pubsub is not None:
            try:
                await pubsub.unsubscribe("channel:ui_updates")
            except Exception:
                pass
            try:
                await pubsub.close()
            except Exception:
                pass
