import { z } from 'zod'

// ─── Auth ─────────────────────────────────────────────────────────────────────
export const UserSessionSchema = z.object({
    sub: z.string(),
    username: z.string(),
    role: z.enum(['admin', 'user']).or(z.string()),
    xvia_email: z.string().optional().nullable(),
    xvia_username: z.string().optional().nullable(),
})

export type UserSession = z.infer<typeof UserSessionSchema>

// ─── Queue ────────────────────────────────────────────────────────────────────
export const QueueItemSchema = z.object({
    site_id: z.string(),
    resource_id: z.number(),
    protocol: z.string().optional(),
    state: z.string().optional(),
    started_at: z.string().optional(),
    created_at: z.string().optional(),
    nif: z.string().optional(),
    nombre: z.string().optional(),
})

export type QueueItem = z.infer<typeof QueueItemSchema>

export const QueueResponseSchema = z.object({
    items: z.array(QueueItemSchema),
    total: z.number().optional(),
})

// ─── Incidents ────────────────────────────────────────────────────────────────
export const IncidentStatusSchema = z.enum(['NEW', 'REVIEWED', 'RESOLVED'])

export const IncidentItemSchema = z.object({
    id: z.string(),
    site_id: z.string(),
    resource_id: z.number().optional(),
    incident_type: z.string(),
    error_code: z.string().optional(),
    reason: z.string().optional(),
    status: IncidentStatusSchema.optional(),
    claimed_by: z.string().optional(),
    updated_at: z.string().optional(),
    created_at: z.string().optional(),
})

export type IncidentItem = z.infer<typeof IncidentItemSchema>
export type IncidentStatus = z.infer<typeof IncidentStatusSchema>

export const IncidentsResponseSchema = z.object({
    incidents: z.array(IncidentItemSchema),
    total: z.number().optional(),
})

// ─── Control ─────────────────────────────────────────────────────────────────
export const ProcessStatusSchema = z.object({
    name: z.string(),
    status: z.enum(['running', 'stopped', 'error', 'unknown']),
    pid: z.number().optional(),
    uptime: z.number().optional(),
})

export type ProcessStatus = z.infer<typeof ProcessStatusSchema>

export const ControlStatusSchema = z.record(z.string(), ProcessStatusSchema)
export type ControlStatus = z.infer<typeof ControlStatusSchema>

// ─── Config ───────────────────────────────────────────────────────────────────
export const OrganismoConfigSchema = z.object({
    site_id: z.string(),
    query_organisme: z.string().optional(),
    filtro_texp: z.string().optional(),
    regex_expediente: z.string().optional(),
    active: z.boolean(),
})

export type OrganismoConfig = z.infer<typeof OrganismoConfigSchema>

// ─── WebSocket Events ─────────────────────────────────────────────────────────
export const WsEventSchema = z.object({
    type: z.string(),
    data: z.unknown().optional(),
    timestamp: z.string().optional(),
})

export type WsEvent = z.infer<typeof WsEventSchema>
