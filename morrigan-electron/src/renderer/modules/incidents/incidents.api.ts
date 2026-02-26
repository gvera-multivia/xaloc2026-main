import { apiClient } from '@/core/api/client'
import { INCIDENTS } from '@/core/api/endpoints'
import type { IncidentItem } from '@/core/api/schemas'
import { IncidentsResponseSchema } from '@/core/api/schemas'

export const incidentsApi = {
    async getIncidents(): Promise<IncidentItem[]> {
        const res = await apiClient.get(INCIDENTS.LIST)
        const parsed = IncidentsResponseSchema.parse(res.data)

        // Retornamos las incidencias, preferiblemente ordenadas por más recientes y que no estén resueltas
        return parsed.incidents.filter(i => i.status !== 'RESOLVED').sort((a, b) => {
            const dateA = new Date(a.created_at || '').getTime()
            const dateB = new Date(b.created_at || '').getTime()
            return dateB - dateA
        })
    }
}
