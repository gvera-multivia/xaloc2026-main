'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/AuthContext';

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await login(username, password);
      router.replace('/');
    } catch {
      setError('Credenciales invalidas.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen grid place-items-center px-4">
      <div className="w-full max-w-md morr-card rounded-2xl p-8 border border-border/70 bg-[rgba(11,12,16,0.85)]">
        <h1 className="text-2xl font-black uppercase tracking-[0.08em]">Login Dashboard</h1>
        <p className="text-sm text-muted-foreground/80 mt-2">Accede con tu usuario para operar el panel.</p>

        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <div className="space-y-2">
            <label className="text-xs font-black uppercase tracking-[0.16em] text-muted-foreground/80">
              Usuario
            </label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              className="w-full rounded-xl border border-border/70 bg-[rgba(17,19,26,0.55)] px-4 py-2.5 outline-none focus:border-[rgba(108,77,255,0.35)] transition"
            />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-black uppercase tracking-[0.16em] text-muted-foreground/80">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="w-full rounded-xl border border-border/70 bg-[rgba(17,19,26,0.55)] px-4 py-2.5 outline-none focus:border-[rgba(108,77,255,0.35)] transition"
            />
          </div>

          {error && <div className="text-sm text-red-400">{error}</div>}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-xl bg-[color:var(--morr-fate)] text-white py-2.5 text-sm font-black uppercase tracking-[0.14em] hover:bg-[color:var(--morr-fate-hi)] transition disabled:opacity-50"
          >
            {submitting ? 'Validando...' : 'Entrar'}
          </button>
        </form>
      </div>
    </div>
  );
}
