import re

with open('dashboard-frontend/app/blacklist/page.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''            await blacklistApi.block(
                newSiteId.trim(),
                resourceId,
                newReason.trim() || 'Bloqueo manual desde dashboard',
                'manual'
            );
            sileo.success({ title: 'Bloqueo creado', description: `${newSiteId} #${resourceId}` });'''

import re
content_norm = content.replace('\r\n', '\n')
target_norm = target.replace('\r\n', '\n')

replacement = '''            const res = await blacklistApi.block(
                newSiteId.trim(),
                resourceId,
                newReason.trim() || 'Bloqueo manual desde dashboard',
                'manual'
            );
            const extraMsg = res.queue_removed ? " y eliminado de la cola" : "";
            sileo.success({ title: 'Bloqueo creado', description: `${newSiteId} #${resourceId}${extraMsg}` });'''

if target_norm in content_norm:
    new_content = content_norm.replace(target_norm, replacement)
    with open('dashboard-frontend/app/blacklist/page.tsx', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Replaced successfully')
else:
    print('Target not found')
