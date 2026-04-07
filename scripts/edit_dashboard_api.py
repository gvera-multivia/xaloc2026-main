import re

with open('dashboard_api.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add the helper function above the api_blacklist_block definition
helper_function = '''
async def _background_deselect_xvia(id_recurso: int) -> None:
    """Helper to deselect a resource from XVIA in the background."""
    try:
        email = (os.getenv("XVIA_EMAIL") or "").strip()
        password = (os.getenv("XVIA_PASSWORD") or "").strip()
        if not email or not password:
            logger.warning("No credentials found for XVIA_EMAIL/XVIA_PASSWORD. Cannot deselect.")
            return

        async with aiohttp.ClientSession() as session:
            await create_authenticated_session_in_place(session, email, password)
            await deselect_resource(session, id_recurso)
    except Exception as exc:
        logger.error("Background XVIA deselect failed for resource %s: %s", id_recurso, exc)

@app.post("/api/blacklist")
async def api_blacklist_block(payload: dict[str, Any] = Body(...), _user: dict = Depends(require_user)) -> dict:'''

target = '''@app.post("/api/blacklist")
async def api_blacklist_block(payload: dict[str, Any] = Body(...), _user: dict = Depends(require_user)) -> dict:'''

content_norm = content.replace('\r\n', '\n')
target_norm = target.replace('\r\n', '\n')
helper_function_norm = helper_function.replace('\r\n', '\n')

if target_norm in content_norm:
    content_norm = content_norm.replace(target_norm, helper_function_norm)
else:
    print('Target not found for helper function')

# Now add the task inside the endpoint
target2 = '''        source = payload.get("source") or "manual"
        return service.block_blacklist(
            site_id=site_id,
            resource_id=resource_id,
            reason=reason,
            source=source,
        )'''

replacement2 = '''        source = payload.get("source") or "manual"
        
        # Fire background task to deselect from XVIA
        asyncio.create_task(_background_deselect_xvia(resource_id))
        
        return service.block_blacklist(
            site_id=site_id,
            resource_id=resource_id,
            reason=reason,
            source=source,
        )'''

target2_norm = target2.replace('\r\n', '\n')
replacement2_norm = replacement2.replace('\r\n', '\n')

if target2_norm in content_norm:
    content_norm = content_norm.replace(target2_norm, replacement2_norm)
    with open('dashboard_api.py', 'w', encoding='utf-8') as f:
        f.write(content_norm)
    print('Replaced successfully')
else:
    print('Target 2 not found')
