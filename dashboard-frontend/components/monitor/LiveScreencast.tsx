"use client";

import React, { useEffect, useState } from "react";
import { Monitor, RefreshCw } from "lucide-react";

interface LiveScreencastProps {
  live?: boolean;
}

/**
 * MORRIGAN LiveScreencast
 * - Surfaces: Raven/Obsidian
 * - Violet only in transitions/edges (hover/focus)
 * - Idle state: "monitor off" + faint raven silhouette + single crimson eye pulse
 * - Live state: minimal “LIVE” chip + controlled refresh
 */
export default function LiveScreencast({ live = false }: LiveScreencastProps) {
  const [now, setNow] = useState(Date.now());
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(timer);
  }, [live]);

  const onRefresh = () => {
    setNow(Date.now());
    setLoading(true);
    setError(false);
  };

  return (
    <div
      className={[
        "relative overflow-hidden",
        "min-h-[500px] rounded-2xl",
        "morr-card morr-edge",
        "transition-all duration-500",
      ].join(" ")}
      style={{
        // Force the “monitor glass” to feel off & matte
        background:
          "linear-gradient(180deg, rgba(17,19,26,0.55), rgba(11,12,16,0.86))",
      }}
    >
      {/* --- LIVE HUD (minimal) --- */}
      {live && (
        <div className="absolute top-5 left-5 z-20 flex items-center gap-2 rounded-full border border-border/70 bg-[rgba(11,12,16,0.55)] backdrop-blur-md px-4 py-2">
          <span
            className="h-2.5 w-2.5 rounded-full"
            style={{
              background: "var(--morr-fate)",
              boxShadow: "0 0 10px rgba(122, 15, 30, 0.35)",
            }}
          />
          <span className="text-[10px] font-black uppercase tracking-[0.22em] text-foreground/90 flex items-center gap-2">
            <Monitor size={14} className="text-foreground/70" />
            LIVE
          </span>
        </div>
      )}

      {live && (
        <div className="absolute top-5 right-5 z-20">
          <button
            onClick={onRefresh}
            className={[
              "morr-focus",
              "rounded-xl border border-border/70",
              "bg-[rgba(11,12,16,0.55)] backdrop-blur-md",
              "p-2 transition active:scale-[0.99]",
              "hover:border-[rgba(108,77,255,0.32)]",
            ].join(" ")}
            aria-label="Refrescar monitor"
          >
            <RefreshCw
              size={16}
              className={loading && !error ? "animate-spin text-foreground/80" : "text-foreground/80"}
            />
          </button>
        </div>
      )}

      {/* --- CONTENT --- */}
      {!live ? (
        // =========================
        // IDLE: Monitor OFF + Raven Eye
        // =========================
        <div className="absolute inset-0 flex items-center justify-center">
          {/* Matte dark screen */}
          <div className="absolute inset-0 bg-[rgba(0,0,0,0.35)]" />

          {/* Subtle "glass" reflection (very faint) */}
          <div
            className="absolute inset-0 opacity-[0.22]"
            style={{
              background:
                "radial-gradient(900px 420px at 40% -10%, rgba(108,77,255,0.10), transparent 60%)",
            }}
          />

          {/* Faint raven silhouette (almost invisible) */}
          <svg
            className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-[0.06]"
            width="560"
            height="240"
            viewBox="0 0 560 240"
            fill="none"
            aria-hidden="true"
          >
            {/* Minimal side raven silhouette — abstract, not illustrative */}
            <path
              d="M160 150c42-44 112-78 190-78 36 0 70 6 102 18-26 10-44 24-56 40 22 4 38 10 50 18-38 8-78 12-120 12-60 0-118-8-166-26z"
              fill="rgba(255,255,255,0.9)"
            />
            <path
              d="M344 92c18-16 44-24 74-24 18 0 34 3 48 9-22 2-40 8-52 18 14 2 26 6 36 10-24 6-50 9-78 9-12 0-22-1-28-2 0-8 0-14 0-20z"
              fill="rgba(255,255,255,0.9)"
            />
          </svg>

          {/* The Eye (calm, intimidating, addictive) */}
          <div className="relative z-10 flex flex-col items-center">
            <div className="relative">
              <span
                className="block h-2.5 w-2.5 rounded-full"
                style={{
                  background: "var(--morr-fate-hi)",
                  animation: "morr-eye 6.5s ease-in-out infinite",
                  boxShadow: "0 0 14px rgba(139, 15, 26, 0.24)",
                }}
              />
              {/* tiny inner heat (tight) */}
              <span
                className="absolute inset-0 rounded-full"
                style={{
                  boxShadow: "0 0 22px rgba(122, 15, 30, 0.14)",
                }}
              />
            </div>

            {/* Minimal copy */}
            <div className="mt-6 text-center">
              <h4 className="text-lg font-black uppercase tracking-tight text-foreground/85">
                Monitor en Reposo
              </h4>
              <p className="mt-1 text-sm text-muted-foreground/70 max-w-[280px]">
                No hay tareas en ejecución en este momento.
              </p>
              <p className="mt-4 text-[11px] uppercase tracking-[0.22em] text-muted-foreground/60">
                Watching.
              </p>
            </div>
          </div>
        </div>
      ) : error ? (
        // =========================
        // LIVE: Error state (quiet)
        // =========================
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-10">
          <div className="text-sm text-muted-foreground/80">
            No hay señal de video activa
          </div>
          <div className="mt-2 text-[11px] uppercase tracking-[0.22em] text-muted-foreground/60">
            The Watcher is blind.
          </div>
        </div>
      ) : (
        // =========================
        // LIVE: Screencast image
        // =========================
        <img
          src={`/api/queue/live-screenshot?t=${now}`}
          alt="Live Screencast"
          className="absolute inset-0 w-full h-full object-contain transition-opacity duration-500"
          onLoad={() => setLoading(false)}
          onError={() => {
            setError(true);
            setLoading(false);
          }}
          style={{
            opacity: loading ? 0 : 1,
          }}
        />
      )}

      {/* Loading overlay (live only) */}
      {live && loading && !error && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-[rgba(0,0,0,0.25)]">
          <div className="h-10 w-10 rounded-full border border-[rgba(108,77,255,0.20)] border-t-[rgba(108,77,255,0.65)] animate-spin" />
        </div>
      )}

      {/* Optional subtle scan line when live (adds addictiveness, very faint) */}
      {live && !loading && !error && (
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.10]"
          style={{
            background:
              "linear-gradient(90deg, transparent, rgba(108,77,255,0.35), transparent)",
            height: "1px",
            top: "20%",
            animation: "morr-scan 10s ease-in-out infinite",
          }}
        />
      )}
    </div>
  );
}
