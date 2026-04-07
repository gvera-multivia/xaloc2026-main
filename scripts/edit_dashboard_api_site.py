import re

with open('dashboard_api.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''        site_id = str(payload.get("site_id") or "").strip()'''
replacement = '''        site_id = str(payload.get("site_id") or "global").strip()'''

content_norm = content.replace('\r\n', '\n')
target_norm = target.replace('\r\n', '\n')
replacement_norm = replacement.replace('\r\n', '\n')

if target_norm in content_norm:
    content_norm = content_norm.replace(target_norm, replacement_norm)
    with open('dashboard_api.py', 'w', encoding='utf-8') as f:
        f.write(content_norm)
    print("Replaced API site_id default successfully")
else:
    print("API target not found")
