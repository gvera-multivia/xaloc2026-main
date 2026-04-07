import re

with open('dashboard/services.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''        self.admin_store.block_resource(
            site_id=site,
            resource_id=rid,
            reason=(reason or "").strip() or None,
            source=(source or "").strip() or "manual",
        )
        return {"site_id": site, "resource_id": rid, "blocked": True}'''

import re
# Normalize both to \n for match
content_norm = content.replace('\r\n', '\n')
target_norm = target.replace('\r\n', '\n')

replacement = '''        self.admin_store.block_resource(
            site_id=site,
            resource_id=rid,
            reason=(reason or "").strip() or None,
            source=(source or "").strip() or "manual",
        )
        
        queue_removed = False
        try:
            res = self.remove_queue_item(site_id=site, resource_id=rid)
            queue_removed = res.get("removed", False)
        except Exception as exc:
            self.logger.warning("No se pudo remover el recurso %s de las colas tras bloqueo: %s", rid, exc)
            
        return {"site_id": site, "resource_id": rid, "blocked": True, "queue_removed": queue_removed}'''

if target_norm in content_norm:
    new_content = content_norm.replace(target_norm, replacement)
    with open('dashboard/services.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Replaced successfully')
else:
    print('Target not found')
