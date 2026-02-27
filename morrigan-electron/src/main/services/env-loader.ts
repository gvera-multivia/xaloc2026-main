/// <reference types="node" />
import fs from 'node:fs'
import path from 'node:path'

let loaded = false

function parseEnvContent(content: string): Record<string, string> {
    const values: Record<string, string> = {}
    for (const rawLine of content.split(/\r?\n/)) {
        const line = rawLine.trim()
        if (!line || line.startsWith('#')) {
            continue
        }
        const idx = line.indexOf('=')
        if (idx <= 0) {
            continue
        }
        const key = line.slice(0, idx).trim()
        if (!key) {
            continue
        }
        let value = line.slice(idx + 1).trim()
        if (
            (value.startsWith('"') && value.endsWith('"')) ||
            (value.startsWith("'") && value.endsWith("'"))
        ) {
            value = value.slice(1, -1)
        }
        values[key] = value
    }
    return values
}

export function loadMainEnv(): void {
    if (loaded) {
        return
    }

    const candidates = [
        path.resolve(process.cwd(), '.env'),
        path.resolve(process.cwd(), 'morrigan-electron', '.env'),
        path.resolve(__dirname, '..', '..', '..', '.env'),
    ]

    for (const envPath of candidates) {
        if (!fs.existsSync(envPath)) {
            continue
        }
        try {
            const raw = fs.readFileSync(envPath, 'utf-8')
            const parsed = parseEnvContent(raw)
            for (const [key, value] of Object.entries(parsed)) {
                if (process.env[key] === undefined) {
                    process.env[key] = value
                }
            }
            loaded = true
            return
        } catch {
            // Non-fatal: try next candidate.
        }
    }

    loaded = true
}
