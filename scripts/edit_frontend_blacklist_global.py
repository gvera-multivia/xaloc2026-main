import re

with open('dashboard-frontend/app/blacklist/page.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove state declaration
target1 = '''    const [newSiteId, setNewSiteId] = useState('');'''
replacement1 = ''''''

# Remove validation for site
target2 = '''        const resourceId = Number(newResourceId);
        if (!newSiteId.trim()) {
            setError('Debes indicar un site.');
            return;
        }'''
replacement2 = '''        const resourceId = Number(newResourceId);'''

# Change loader state
target3 = '''        setBusy(`new-${newSiteId}-${resourceId}`);'''
replacement3 = '''        setBusy(`new-global-${resourceId}`);'''

# Change the blacklistApi.block call
target4 = '''            const res = await blacklistApi.block(
                newSiteId.trim(),
                resourceId,
                newReason.trim() || 'Bloqueo manual desde dashboard',
                'manual'
            );'''
replacement4 = '''            const res = await blacklistApi.block(
                'global',
                resourceId,
                newReason.trim() || 'Bloqueo manual desde dashboard',
                'manual'
            );'''

# Update toast
target5 = '''            sileo.success({ title: 'Bloqueo creado', description: `${newSiteId} #${resourceId}${extraMsg}` });'''
replacement5 = '''            sileo.success({ title: 'Bloqueo creado', description: `#${resourceId}${extraMsg}` });'''

# Remove disabled busy check with siteId
target6 = '''                            disabled={busy === `new-${newSiteId}-${Number(newResourceId)}`}'''
replacement6 = '''                            disabled={busy === `new-global-${Number(newResourceId)}`}'''

# Remove <label> with <select> for site
target7 = '''                        <label className="text-xs text-muted-foreground space-y-1">
                            <span>Site (Organismo)</span>
                            <select
                                value={newSiteId}
                                onChange={(e) => setNewSiteId(e.target.value)}
                                className="w-full bg-background border border-border rounded-xl px-3 py-2 text-sm appearance-none cursor-pointer"
                            >
                                <option value="" disabled>Selecciona un site...</option>
                                {knownSites.map((site) => (
                                    <option key={site} value={site}>{site}</option>
                                ))}
                            </select>
                        </label>'''

replacement7 = ''''''

targets = [target1, target2, target3, target4, target5, target6, target7]
replacements = [replacement1, replacement2, replacement3, replacement4, replacement5, replacement6, replacement7]

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
