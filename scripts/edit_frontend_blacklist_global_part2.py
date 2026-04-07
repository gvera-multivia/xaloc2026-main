import re

with open('dashboard-frontend/app/blacklist/page.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

target1 = '''    const [newSiteId, setNewSiteId] = useState('ayunta_palma');'''
replacement1 = ''''''

target2 = '''                        <label className="text-xs text-muted-foreground space-y-1">
                            <span>Site</span>
                            <select
                                value={newSiteId}
                                onChange={(e) => setNewSiteId(e.target.value)}
                                className="w-full bg-background border border-border rounded-xl px-3 py-2 text-sm"
                            >
                                {knownSites.map((site) => (
                                    <option key={site} value={site}>{site}</option>
                                ))}
                            </select>
                        </label>'''
replacement2 = ''''''

# The `grid-cols-1 md:grid-cols-3` needs to become `md:grid-cols-2` because we removed one column
target3 = '''                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">'''
replacement3 = '''                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">'''

targets = [target1, target2, target3]
replacements = [replacement1, replacement2, replacement3]

content_norm = content.replace('\r\n', '\n')
for t, r in zip(targets, replacements):
    tn = t.replace('\r\n', '\n')
    rn = r.replace('\r\n', '\n')
    if tn in content_norm:
        content_norm = content_norm.replace(tn, rn)
    else:
        print(f"Target not found: {tn[:50]}...")

with open('dashboard-frontend/app/blacklist/page.tsx', 'w', encoding='utf-8') as f:
    f.write(content_norm)
print("Frontend updated successfully")
