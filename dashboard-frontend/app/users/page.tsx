'use client';

import React, { useEffect, useState } from 'react';
import { usersApi } from '@/lib/api';
import { DashboardUser } from '@/lib/types';

export default function UsersPage() {
  const [items, setItems] = useState<DashboardUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<'admin' | 'user'>('user');
  const [active, setActive] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try {
      const res = await usersApi.list();
      setItems((res.items || []) as DashboardUser[]);
      setError('');
    } catch {
      setError('No se pudo cargar la lista de usuarios.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    setSuccess('');
    setError('');
    setBusy(true);
    try {
      await usersApi.create({
        username: username.trim(),
        password,
        role,
        active,
      });
      setSuccess('Usuario creado correctamente.');
      setUsername('');
      setPassword('');
      setRole('user');
      setActive(true);
      await refresh();
    } catch (e: any) {
      const msg = String(e?.message || '').trim();
      setError(msg || 'No se pudo crear el usuario.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h2 className="text-2xl font-black uppercase tracking-tight">Usuarios</h2>
        <p className="text-xs text-muted-foreground/70 uppercase tracking-[0.16em] mt-1">
          Alta y revisión de cuentas del dashboard
        </p>
      </div>

      <section className="morr-card rounded-2xl p-6 border border-border/70">
        <h3 className="text-sm font-black uppercase tracking-[0.16em] mb-4">Crear Usuario</h3>
        <form onSubmit={handleCreate} className="grid grid-cols-1 md:grid-cols-5 gap-3">
          <input
            placeholder="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="rounded-xl border border-border/70 bg-[rgba(17,19,26,0.55)] px-3 py-2 text-sm outline-none focus:border-[rgba(108,77,255,0.35)]"
          />
          <input
            placeholder="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded-xl border border-border/70 bg-[rgba(17,19,26,0.55)] px-3 py-2 text-sm outline-none focus:border-[rgba(108,77,255,0.35)]"
          />
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as 'admin' | 'user')}
            className="rounded-xl border border-border/70 bg-[rgba(17,19,26,0.55)] px-3 py-2 text-sm outline-none focus:border-[rgba(108,77,255,0.35)]"
          >
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
          <label className="rounded-xl border border-border/70 bg-[rgba(17,19,26,0.55)] px-3 py-2 text-sm flex items-center gap-2">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            active
          </label>
          <button
            type="submit"
            disabled={busy}
            className="rounded-xl bg-[color:var(--morr-fate)] text-white text-sm font-black uppercase tracking-[0.12em] px-4 py-2 hover:bg-[color:var(--morr-fate-hi)] transition disabled:opacity-50"
          >
            {busy ? 'Creando...' : 'Crear'}
          </button>
        </form>

        {error && <div className="mt-3 text-sm text-red-400">{error}</div>}
        {success && <div className="mt-3 text-sm text-emerald-400">{success}</div>}
      </section>

      <section className="morr-card rounded-2xl border border-border/70 overflow-hidden">
        <div className="px-6 py-4 border-b border-border/70 flex items-center justify-between">
          <h3 className="text-sm font-black uppercase tracking-[0.16em]">Listado</h3>
          <button
            onClick={refresh}
            className="rounded-lg border border-border/70 px-3 py-1.5 text-xs uppercase tracking-[0.12em] hover:border-[rgba(108,77,255,0.35)] transition"
          >
            Refrescar
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-[rgba(17,19,26,0.55)] text-xs uppercase tracking-[0.12em] text-muted-foreground/80">
                <th className="text-left px-6 py-3">ID</th>
                <th className="text-left px-6 py-3">Username</th>
                <th className="text-left px-6 py-3">Role</th>
                <th className="text-left px-6 py-3">Active</th>
                <th className="text-left px-6 py-3">Creado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {loading ? (
                <tr>
                  <td className="px-6 py-6 text-muted-foreground" colSpan={5}>
                    Cargando...
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td className="px-6 py-6 text-muted-foreground" colSpan={5}>
                    No hay usuarios.
                  </td>
                </tr>
              ) : (
                items.map((u) => (
                  <tr key={`${u.id}-${u.username}`} className="hover:bg-[rgba(255,255,255,0.03)]">
                    <td className="px-6 py-3 font-mono">{u.id ?? '-'}</td>
                    <td className="px-6 py-3">{u.username}</td>
                    <td className="px-6 py-3 uppercase">{u.role}</td>
                    <td className="px-6 py-3">{Number(u.active ?? 0) === 1 || u.active === true ? 'yes' : 'no'}</td>
                    <td className="px-6 py-3">{u.created_at ? new Date(u.created_at).toLocaleString() : '-'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
