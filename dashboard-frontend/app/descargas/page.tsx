'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { Download, Package, FileJson, Loader2, Plus, Save, Trash2, RefreshCw } from 'lucide-react';
import { electronApi } from '@/lib/api';
import { sileo } from 'sileo';
import { useAuth } from '@/lib/AuthContext';

type DownloadInfo = {
  installerName: string;
  installerSizeBytes: number;
  msiName?: string | null;
  msiSizeBytes?: number | null;
  config: {
    apiBaseUrl: string;
    wsUrl: string;
    bootstrapUrl: string;
    refreshIntervalSec: number;
  };
  downloadUrls: {
    bundleZip: string;
    installer: string;
    installerMsi?: string | null;
    configJson: string;
  };
  user: { username?: string; role?: string };
};

type AlertTemplate = {
  id: string;
  label: string;
  level: 'info' | 'warning' | 'critical';
  title: string;
  body: string;
  created_at?: string;
  updated_at?: string;
};

type TemplateForm = {
  id: string;
  label: string;
  level: 'info' | 'warning' | 'critical';
  title: string;
  body: string;
};

const EMPTY_TEMPLATE_FORM: TemplateForm = {
  id: '',
  label: '',
  level: 'info',
  title: '',
  body: '',
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export default function DescargasPage() {
  const { isAdmin } = useAuth();
  const [loading, setLoading] = useState(true);
  const [info, setInfo] = useState<DownloadInfo | null>(null);
  const [error, setError] = useState('');

  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [templates, setTemplates] = useState<AlertTemplate[]>([]);
  const [templatesOpen, setTemplatesOpen] = useState(false);

  const [sending, setSending] = useState(false);
  const [templateId, setTemplateId] = useState('');
  const [level, setLevel] = useState<'info' | 'warning' | 'critical'>('info');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [internalNote, setInternalNote] = useState('');

  const [editingTemplateId, setEditingTemplateId] = useState('');
  const [templateForm, setTemplateForm] = useState<TemplateForm>(EMPTY_TEMPLATE_FORM);
  const [templateSaving, setTemplateSaving] = useState(false);

  const hasTemplateSelection = templateId.trim().length > 0;

  const selectedTemplate = useMemo(
    () => templates.find((tpl) => tpl.id === templateId) || null,
    [templates, templateId],
  );

  const applyTemplate = (id: string) => {
    const template = templates.find((it) => it.id === id);
    if (!template) return;
    setTemplateId(template.id);
    setLevel(template.level);
    setTitle(template.title);
    setBody(template.body);
  };

  const loadTemplates = async (silent = false) => {
    try {
      if (!silent) setTemplatesLoading(true);
      const res = await electronApi.listAlertTemplates();
      const items = Array.isArray(res.items) ? res.items : [];
      setTemplates(items);

      if (items.length > 0) {
        const alreadyValid = items.some((tpl) => tpl.id === templateId);
        if (!alreadyValid) {
          applyTemplate(items[0].id);
        }
      } else {
        setTemplateId('');
      }
    } catch (err: any) {
      sileo.error({ title: 'Plantillas no disponibles', description: String(err?.message || 'Error desconocido') });
    } finally {
      if (!silent) setTemplatesLoading(false);
    }
  };

  const loadDownloadInfo = async () => {
    try {
      const data = await electronApi.getDownloadInfo();
      setInfo(data);
      setError('');
    } catch (err: any) {
      const detail = String(err?.message || 'No se pudo cargar el paquete de descargas.');
      setError(detail);
      sileo.error({ title: 'Descargas no disponibles', description: detail });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadDownloadInfo();
    if (isAdmin) {
      void loadTemplates();
    }
  }, [isAdmin]);

  const resetTemplateForm = () => {
    setEditingTemplateId('');
    setTemplateForm(EMPTY_TEMPLATE_FORM);
  };

  const beginEditTemplate = (tpl: AlertTemplate) => {
    setEditingTemplateId(tpl.id);
    setTemplateForm({
      id: tpl.id,
      label: tpl.label,
      level: tpl.level,
      title: tpl.title,
      body: tpl.body,
    });
  };

  const saveTemplate = async () => {
    const payload = {
      id: templateForm.id.trim(),
      label: templateForm.label.trim(),
      title: templateForm.title.trim(),
      body: templateForm.body.trim(),
      level: templateForm.level,
    };

    if (!payload.id || !payload.label || !payload.title || !payload.body) {
      sileo.error({ title: 'Campos obligatorios', description: 'ID, etiqueta, titulo y cuerpo son obligatorios.' });
      return;
    }

    try {
      setTemplateSaving(true);
      if (editingTemplateId) {
        await electronApi.updateAlertTemplate(editingTemplateId, {
          label: payload.label,
          title: payload.title,
          body: payload.body,
          level: payload.level,
        });
        sileo.success({ title: 'Plantilla actualizada', description: payload.label });
      } else {
        await electronApi.createAlertTemplate(payload);
        sileo.success({ title: 'Plantilla creada', description: payload.label });
      }
      await loadTemplates(true);
      resetTemplateForm();
    } catch (err: any) {
      sileo.error({ title: 'No se pudo guardar', description: String(err?.message || 'Error desconocido') });
    } finally {
      setTemplateSaving(false);
    }
  };

  const deleteTemplate = async (id: string) => {
    if (!confirm(`Eliminar plantilla '${id}'?`)) return;
    try {
      await electronApi.deleteAlertTemplate(id);
      sileo.success({ title: 'Plantilla eliminada', description: id });
      await loadTemplates(true);
      if (editingTemplateId === id) {
        resetTemplateForm();
      }
    } catch (err: any) {
      sileo.error({ title: 'No se pudo eliminar', description: String(err?.message || 'Error desconocido') });
    }
  };

  const sendAlert = async () => {
    if (!title.trim() || !body.trim()) {
      sileo.error({ title: 'Campos obligatorios', description: 'Titulo y mensaje son obligatorios.' });
      return;
    }
    try {
      setSending(true);
      const res = await electronApi.broadcastAlert({
        title: title.trim(),
        body: body.trim(),
        level,
        internal_note: internalNote.trim() || undefined,
        template_id: templateId || undefined,
      });
      sileo.success({
        title: 'Alerta enviada',
        description: `Notificacion publicada. Subscriptores activos: ${res.published_to_subscribers}`,
      });
    } catch (err: any) {
      sileo.error({
        title: 'No se pudo enviar la alerta',
        description: String(err?.message || 'Error desconocido'),
      });
    } finally {
      setSending(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
        Cargando paquete de descargas...
      </div>
    );
  }

  if (error || !info) {
    return (
      <div className="space-y-4">
        <h2 className="text-2xl font-black uppercase tracking-tight">Descargas</h2>
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-4 text-sm">
          {error || 'No hay paquete disponible.'}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-black uppercase tracking-tight">Electron</h2>
        <p className="text-xs text-muted-foreground/70 uppercase tracking-[0.14em] mt-1">
          Distribucion y control operativo de la app Electron de Morrigan.
        </p>
      </div>

      <div className="rounded-xl border border-border/70 bg-[rgba(17,19,26,0.55)] p-5 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-black">Instalador recomendado</div>
            <div className="text-xs text-muted-foreground">
              Descarga directa del instalador (.exe), para doble clic y ejecutar.
            </div>
          </div>
          <a
            href={info.downloadUrls.installer}
            className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-xs font-black uppercase tracking-[0.15em] border border-[rgba(108,77,255,0.35)] bg-[rgba(108,77,255,0.12)] hover:bg-[rgba(108,77,255,0.18)] transition"
          >
            <Download size={14} />
            Descargar instalador .exe
          </a>
        </div>

        {info.downloadUrls.installerMsi && (
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-black">Alternativa MSI</div>
              <div className="text-xs text-muted-foreground">
                Instalador .msi para despliegues corporativos o GPO.
              </div>
            </div>
            <a
              href={info.downloadUrls.installerMsi}
              className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-xs font-black uppercase tracking-[0.15em] border border-border/70 hover:border-foreground/40 transition"
            >
              <Download size={14} />
              Descargar instalador .msi
            </a>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
          <div className="rounded-md border border-border/60 bg-background/20 p-3">
            <div className="text-muted-foreground uppercase tracking-wider">Installer</div>
            <div className="font-semibold mt-1">{info.installerName}</div>
            <div className="text-muted-foreground">{formatSize(info.installerSizeBytes)}</div>
          </div>
          {info.msiName && info.msiSizeBytes ? (
            <div className="rounded-md border border-border/60 bg-background/20 p-3">
              <div className="text-muted-foreground uppercase tracking-wider">Installer MSI</div>
              <div className="font-semibold mt-1">{info.msiName}</div>
              <div className="text-muted-foreground">{formatSize(info.msiSizeBytes)}</div>
            </div>
          ) : (
            <div className="rounded-md border border-border/60 bg-background/20 p-3">
              <div className="text-muted-foreground uppercase tracking-wider">Installer MSI</div>
              <div className="font-semibold mt-1">No disponible</div>
              <div className="text-muted-foreground">Generalo con `npm run dist:msi`.</div>
            </div>
          )}
          <div className="rounded-md border border-border/60 bg-background/20 p-3">
            <div className="text-muted-foreground uppercase tracking-wider">Usuario</div>
            <div className="font-semibold mt-1">{info.user?.username || '-'}</div>
            <div className="text-muted-foreground">rol: {info.user?.role || '-'}</div>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-border/70 bg-[rgba(17,19,26,0.55)] p-5 space-y-3">
        <div className="text-sm font-black">Descargas avanzadas</div>
        <div className="flex flex-wrap gap-2">
          <a
            href={info.downloadUrls.bundleZip}
            className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-bold border border-border/70 hover:border-foreground/40 transition"
          >
            <Package size={14} />
            ZIP plug-and-play
          </a>
          <a
            href={info.downloadUrls.configJson}
            className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-bold border border-border/70 hover:border-foreground/40 transition"
          >
            <FileJson size={14} />
            Solo config.json
          </a>
        </div>
      </div>

      <div className="rounded-xl border border-border/70 bg-[rgba(17,19,26,0.55)] p-5">
        <div className="text-sm font-black mb-2">Configuracion inyectada</div>
        <pre className="text-xs overflow-auto rounded-md bg-black/30 p-3 border border-border/60">
{JSON.stringify(info.config, null, 2)}
        </pre>
      </div>

      {isAdmin && (
        <div className="rounded-xl border border-border/70 bg-[rgba(17,19,26,0.55)] p-5 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-black">Centro de Alertas Electron (Admin)</div>
              <div className="text-xs text-muted-foreground mt-1">
                Envia mensajes broadcast a todos los Electron conectados por WebSocket.
              </div>
            </div>
            <button
              className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-bold border border-border/70 hover:border-foreground/40 transition"
              onClick={() => setTemplatesOpen((prev) => !prev)}
              type="button"
            >
              {templatesOpen ? 'Cerrar gestor' : 'Gestionar plantillas'}
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="text-xs">
              <div className="mb-1 text-muted-foreground uppercase tracking-wider">Template</div>
              <select
                className="w-full rounded-md border border-border/70 bg-background/40 p-2"
                value={hasTemplateSelection ? templateId : ''}
                onChange={(e) => applyTemplate(e.target.value)}
                disabled={templatesLoading || templates.length === 0}
              >
                {templates.length === 0 && <option value="">Sin plantillas</option>}
                {templates.map((tpl) => (
                  <option key={tpl.id} value={tpl.id}>{tpl.label}</option>
                ))}
              </select>
            </label>

            <label className="text-xs">
              <div className="mb-1 text-muted-foreground uppercase tracking-wider">Nivel</div>
              <select
                className="w-full rounded-md border border-border/70 bg-background/40 p-2"
                value={level}
                onChange={(e) => setLevel(e.target.value as 'info' | 'warning' | 'critical')}
              >
                <option value="info">info</option>
                <option value="warning">warning</option>
                <option value="critical">critical</option>
              </select>
            </label>
          </div>

          <label className="text-xs block">
            <div className="mb-1 text-muted-foreground uppercase tracking-wider">Titulo alerta</div>
            <input
              className="w-full rounded-md border border-border/70 bg-background/40 p-2"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Titulo visible en notificacion"
            />
          </label>

          <label className="text-xs block">
            <div className="mb-1 text-muted-foreground uppercase tracking-wider">Mensaje</div>
            <textarea
              className="w-full rounded-md border border-border/70 bg-background/40 p-2 min-h-[96px]"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Texto que vera el usuario en Electron"
            />
          </label>

          <label className="text-xs block">
            <div className="mb-1 text-muted-foreground uppercase tracking-wider">Texto interno (admin)</div>
            <textarea
              className="w-full rounded-md border border-border/70 bg-background/40 p-2 min-h-[70px]"
              value={internalNote}
              onChange={(e) => setInternalNote(e.target.value)}
              placeholder="Nota interna (contexto operativo / ticket / motivo)"
            />
          </label>

          <div className="flex justify-end">
            <button
              className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-xs font-black uppercase tracking-[0.12em] border border-[rgba(108,77,255,0.35)] bg-[rgba(108,77,255,0.12)] hover:bg-[rgba(108,77,255,0.18)] transition disabled:opacity-60"
              onClick={sendAlert}
              disabled={sending}
            >
              {sending ? <Loader2 size={14} className="animate-spin" /> : null}
              {sending ? 'Enviando...' : 'Enviar alerta global'}
            </button>
          </div>

          {templatesOpen && (
            <div className="rounded-xl border border-border/70 bg-background/10 p-4 space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-black">Gestor de plantillas</div>
                <button
                  type="button"
                  className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-bold border border-border/70 hover:border-foreground/40 transition"
                  onClick={() => void loadTemplates()}
                  disabled={templatesLoading}
                >
                  {templatesLoading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                  Refrescar
                </button>
              </div>

              <div className="overflow-auto border border-border/60 rounded-md">
                <table className="w-full text-xs">
                  <thead className="bg-black/20">
                    <tr>
                      <th className="text-left p-2">ID</th>
                      <th className="text-left p-2">Etiqueta</th>
                      <th className="text-left p-2">Nivel</th>
                      <th className="text-right p-2">Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {templates.map((tpl) => (
                      <tr key={tpl.id} className="border-t border-border/40">
                        <td className="p-2 font-mono">{tpl.id}</td>
                        <td className="p-2">{tpl.label}</td>
                        <td className="p-2">{tpl.level}</td>
                        <td className="p-2 text-right space-x-2">
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 rounded-md px-2 py-1 border border-border/70 hover:border-foreground/40"
                            onClick={() => beginEditTemplate(tpl)}
                          >
                            <Save size={12} />
                            Editar
                          </button>
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 rounded-md px-2 py-1 border border-red-500/50 text-red-300 hover:bg-red-500/10"
                            onClick={() => void deleteTemplate(tpl.id)}
                          >
                            <Trash2 size={12} />
                            Borrar
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <label className="text-xs block">
                  <div className="mb-1 text-muted-foreground uppercase tracking-wider">ID</div>
                  <input
                    className="w-full rounded-md border border-border/70 bg-background/40 p-2 font-mono"
                    value={templateForm.id}
                    onChange={(e) => setTemplateForm((prev) => ({ ...prev, id: e.target.value }))}
                    placeholder="maintenance"
                    disabled={Boolean(editingTemplateId)}
                  />
                </label>
                <label className="text-xs block">
                  <div className="mb-1 text-muted-foreground uppercase tracking-wider">Etiqueta</div>
                  <input
                    className="w-full rounded-md border border-border/70 bg-background/40 p-2"
                    value={templateForm.label}
                    onChange={(e) => setTemplateForm((prev) => ({ ...prev, label: e.target.value }))}
                    placeholder="Mantenimiento programado"
                  />
                </label>
                <label className="text-xs block">
                  <div className="mb-1 text-muted-foreground uppercase tracking-wider">Nivel</div>
                  <select
                    className="w-full rounded-md border border-border/70 bg-background/40 p-2"
                    value={templateForm.level}
                    onChange={(e) => setTemplateForm((prev) => ({ ...prev, level: e.target.value as 'info' | 'warning' | 'critical' }))}
                  >
                    <option value="info">info</option>
                    <option value="warning">warning</option>
                    <option value="critical">critical</option>
                  </select>
                </label>
                <label className="text-xs block md:col-span-2">
                  <div className="mb-1 text-muted-foreground uppercase tracking-wider">Titulo</div>
                  <input
                    className="w-full rounded-md border border-border/70 bg-background/40 p-2"
                    value={templateForm.title}
                    onChange={(e) => setTemplateForm((prev) => ({ ...prev, title: e.target.value }))}
                    placeholder="Titulo por defecto"
                  />
                </label>
                <label className="text-xs block md:col-span-2">
                  <div className="mb-1 text-muted-foreground uppercase tracking-wider">Cuerpo</div>
                  <textarea
                    className="w-full rounded-md border border-border/70 bg-background/40 p-2 min-h-[84px]"
                    value={templateForm.body}
                    onChange={(e) => setTemplateForm((prev) => ({ ...prev, body: e.target.value }))}
                    placeholder="Mensaje por defecto"
                  />
                </label>
              </div>

              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-bold border border-border/70 hover:border-foreground/40 transition"
                  onClick={resetTemplateForm}
                >
                  <Plus size={14} />
                  Nueva
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs font-bold border border-[rgba(108,77,255,0.35)] bg-[rgba(108,77,255,0.12)] hover:bg-[rgba(108,77,255,0.18)] transition disabled:opacity-60"
                  onClick={() => void saveTemplate()}
                  disabled={templateSaving}
                >
                  {templateSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                  {editingTemplateId ? 'Guardar cambios' : 'Crear plantilla'}
                </button>
              </div>
            </div>
          )}

          {selectedTemplate && (
            <div className="text-[11px] text-muted-foreground">
              Plantilla activa: <span className="font-semibold">{selectedTemplate.label}</span> ({selectedTemplate.id})
            </div>
          )}
        </div>
      )}
    </div>
  );
}
