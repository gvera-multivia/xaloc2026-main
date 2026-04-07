import re

with open('dashboard/repositories.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''                    WHERE status IN ({self.ACTIVE_STATES_SQL})
                      AND {site_expr} = %s
                      AND {resource_expr} = %s
                    ORDER BY COALESCE(queued_at, started_at, created_at) DESC, id DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (str(site_id), int(resource_id)),
                )'''

replacement = '''                    WHERE status IN ({self.ACTIVE_STATES_SQL})
                      AND {resource_expr} = %s
                    ORDER BY COALESCE(queued_at, started_at, created_at) DESC, id DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (int(resource_id),),
                )'''

content_norm = content.replace('\r\n', '\n')
target_norm = target.replace('\r\n', '\n')
replacement_norm = replacement.replace('\r\n', '\n')

if target_norm in content_norm:
    content_norm = content_norm.replace(target_norm, replacement_norm)
    with open('dashboard/repositories.py', 'w', encoding='utf-8') as f:
        f.write(content_norm)
    print("Replaced cancellation query successfully")
else:
    print("Target not found")
