'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { Crown, Medal, Award, Trophy } from 'lucide-react';
import { historyApi } from '@/lib/api';
import { sileo } from 'sileo';

type TopUserItem = {
  usuario_asignado: string;
  total_recursos: number;
};

const MORRIGAN_LABEL = 'MORRIGAN';

export default function HistoryTopUsersPage() {
  const [items, setItems] = useState<TopUserItem[]>([]);
  const [todayItems, setTodayItems] = useState<TopUserItem[]>([]);
  const [morriganTotal, setMorriganTotal] = useState(0);
  const [morriganTodayTotal, setMorriganTodayTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const now = new Date();
        const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
        const [globalRes, todayRes] = await Promise.all([
          historyApi.getTopUsers(5000),
          historyApi.getTopUsers(5, today),
        ]);
        setItems((globalRes.items || []) as TopUserItem[]);
        setTodayItems((todayRes.items || []).slice(0, 5) as TopUserItem[]);
        setMorriganTotal(Number(globalRes.morrigan_total || 0));
        setMorriganTodayTotal(Number(globalRes.morrigan_today_total || todayRes.morrigan_total || 0));
      } catch {
        sileo.error({ title: 'Error', description: 'No se pudo cargar el ranking de usuarios.' });
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, []);

  const top3 = items.slice(0, 3);

  return (
    <div className="space-y-8 animate-in fade-in duration-700">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black uppercase tracking-tight">Top de Usuarios</h2>
          <p className="text-xs text-muted-foreground/60 uppercase tracking-widest mt-1">Clasificacion por recursos completados (Estado=2).</p>
          <div className="mt-3 flex items-center gap-2">
            <Link
              href="/history"
              className="px-3 py-1.5 rounded-sm text-[10px] font-black uppercase tracking-[0.15em] border border-border/70 bg-[rgba(17,19,26,0.55)] text-muted-foreground/80 hover:text-foreground hover:border-[rgba(108,77,255,0.22)] transition-all"
            >
              Historial
            </Link>
            <Link
              href="/history/top"
              className="px-3 py-1.5 rounded-sm text-[10px] font-black uppercase tracking-[0.15em] border border-[rgba(108,77,255,0.35)] bg-[rgba(108,77,255,0.16)] text-foreground/90"
            >
              Ranking Usuarios
            </Link>
          </div>
        </div>
      </div>

      <div className="morr-card rounded-xl border border-[rgba(108,77,255,0.24)] p-4 bg-[rgba(108,77,255,0.07)]">
        <p className="text-[11px] font-black uppercase tracking-[0.18em] text-foreground/90">
          {MORRIGAN_LABEL} ha hecho <span className="text-[rgba(108,77,255,0.95)]">{morriganTotal}</span> recursos
        </p>
        <p className="text-[11px] text-muted-foreground/80 mt-1">
          Metrica global del historial (se muestra fuera del top de usuarios).
        </p>
        <p className="text-[11px] text-muted-foreground/80 mt-1">
          Hoy ha hecho <span className="text-[rgba(108,77,255,0.95)] font-black">{morriganTodayTotal}</span> recursos.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {top3.map((item, idx) => {
          const rank = idx + 1;
          const icon = rank === 1 ? <Crown size={16} /> : rank === 2 ? <Medal size={16} /> : <Award size={16} />;
          const border = rank === 1
            ? 'border-[rgba(250,204,21,0.45)]'
            : rank === 2
              ? 'border-[rgba(148,163,184,0.45)]'
              : 'border-[rgba(251,146,60,0.45)]';

          return (
            <div key={item.usuario_asignado} className={`morr-card rounded-xl p-4 border ${border} bg-[rgba(17,19,26,0.55)]`}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-black uppercase tracking-[0.16em] text-muted-foreground/70">Top {rank}</span>
                <span className="text-foreground/85">{icon}</span>
              </div>
              <div className="text-sm font-black uppercase tracking-[0.08em] break-all">{item.usuario_asignado}</div>
              <div className="text-xs mt-2 text-muted-foreground/80">{item.total_recursos} recursos</div>
            </div>
          );
        })}
      </div>

      <div className="morr-card morr-edge rounded overflow-hidden">
        <div className="px-6 py-4 border-b border-border/70 bg-[rgba(17,19,26,0.55)]">
          <span className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/80">Top 5 de hoy</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-[rgba(17,19,26,0.45)] border-b border-border/70">
                <th className="px-6 py-3 text-[10px] font-black uppercase tracking-[0.16em] text-muted-foreground/80">Posicion</th>
                <th className="px-6 py-3 text-[10px] font-black uppercase tracking-[0.16em] text-muted-foreground/80">Usuario</th>
                <th className="px-6 py-3 text-[10px] font-black uppercase tracking-[0.16em] text-muted-foreground/80">Total Hoy</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[rgba(255,255,255,0.06)]">
              {loading ? (
                <tr>
                  <td colSpan={3} className="px-6 py-8 text-center text-xs uppercase tracking-widest text-muted-foreground/60">Cargando top del dia...</td>
                </tr>
              ) : todayItems.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-6 py-8 text-center text-xs uppercase tracking-widest text-muted-foreground/60">Hoy no hay registros completados.</td>
                </tr>
              ) : (
                todayItems.map((item, idx) => (
                  <tr key={`today-${item.usuario_asignado}-${idx}`}>
                    <td className="px-6 py-3 text-[11px] font-mono">#{idx + 1}</td>
                    <td className="px-6 py-3 text-[11px] font-bold uppercase tracking-[0.04em]">{item.usuario_asignado}</td>
                    <td className="px-6 py-3 text-[11px] font-mono">{item.total_recursos}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="morr-card morr-edge rounded overflow-hidden">
        <div className="px-6 py-4 border-b border-border/70 bg-[rgba(17,19,26,0.55)] flex items-center gap-2">
          <Trophy size={14} className="text-muted-foreground/70" />
          <span className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/80">Clasificacion completa</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-[rgba(17,19,26,0.45)] border-b border-border/70">
                <th className="px-6 py-3 text-[10px] font-black uppercase tracking-[0.16em] text-muted-foreground/80">Posicion</th>
                <th className="px-6 py-3 text-[10px] font-black uppercase tracking-[0.16em] text-muted-foreground/80">Usuario</th>
                <th className="px-6 py-3 text-[10px] font-black uppercase tracking-[0.16em] text-muted-foreground/80">Total Recursos</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[rgba(255,255,255,0.06)]">
              {loading ? (
                <tr>
                  <td colSpan={3} className="px-6 py-10 text-center text-xs uppercase tracking-widest text-muted-foreground/60">Cargando ranking...</td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-6 py-10 text-center text-xs uppercase tracking-widest text-muted-foreground/60">Sin datos para mostrar.</td>
                </tr>
              ) : (
                items.map((item, idx) => {
                  const rank = idx + 1;
                  return (
                    <tr key={`${item.usuario_asignado}-${idx}`}>
                      <td className="px-6 py-3 text-[11px] font-mono">#{rank}</td>
                      <td className="px-6 py-3 text-[11px] font-bold uppercase tracking-[0.04em]">{item.usuario_asignado}</td>
                      <td className="px-6 py-3 text-[11px] font-mono">{item.total_recursos}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
