"use client";

import React, { useEffect, useState } from "react";
import { Monitor, RefreshCw } from "lucide-react";

interface LiveScreencastProps {
  live?: boolean;
}

/**
 * MORRIGAN LiveScreencast - Refactored
 * Raven silhouette upgraded to a detailed, atmospheric profile.
 */
export default function LiveScreencast({ live = false }: LiveScreencastProps) {
  const [now, setNow] = useState(Date.now());
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, [live]);

  const onRefresh = () => {
    setNow(Date.now());
    setLoading(true);
    setError(false);
  };

  return (
    <div
      className="relative overflow-hidden min-h-[500px] rounded morr-card morr-edge transition-all duration-500"
      style={{
        background: "linear-gradient(180deg, rgba(17,19,26,0.55), rgba(11,12,16,0.86))",
      }}
    >
      {/* --- LIVE HUD --- */}
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
            className="morr-focus rounded-xl border border-border/70 bg-[rgba(11,12,16,0.55)] backdrop-blur-md p-2 transition active:scale-[0.99] hover:border-[rgba(108,77,255,0.32)]"
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
        <div className="absolute inset-0 flex items-center justify-center">
          {/* Matte dark screen overlay */}
          <div className="absolute inset-0 bg-[rgba(0,0,0,0.45)]" />

          {/* Detailed Raven Silhouette */}
          <div className="absolute inset-0 flex items-center justify-center opacity-[0.08] pointer-events-none">
            <svg
              viewBox="0 0 1000 600"
              className="w-full h-full max-w-[800px]"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <defs>
                <radialGradient id="ravenGradient" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stopColor="white" stopOpacity="1" />
                  <stop offset="100%" stopColor="white" stopOpacity="0" />
                </radialGradient>
              </defs>
              <path
                d="M850,300 C800,280 720,250 650,240 C580,230 500,220 420,260 C340,300 280,380 250,450 C230,500 200,550 150,580 L900,580 C950,500 900,320 850,300 Z"
                fill="url(#ravenGradient)"
              />
              {/* Detailed Head and Beak Profile */}
              <path
                d="M668,242 C685,220 720,185 715,140 C710,95 660,65 600,60 C540,55 480,80 440,120 C400,160 380,210 395,255 C370,245 320,235 280,250 C240,265 210,310 200,350 C230,335 280,330 320,345 C340,352 365,370 380,400"
                stroke="white"
                strokeWidth="2"
                strokeLinecap="round"
                opacity="0.5"
              />
              <path
                d="M715,140 C760,145 820,170 850,210 C830,205 780,200 745,215"
                stroke="white"
                strokeWidth="3"
                strokeLinecap="round"
              />
            </svg>
          </div>

          {/* The Eye & Text Overlay */}
          <div className="relative z-10 flex flex-col items-center">
            {/* Crimson Pulsing Eye - Positioned relative to where the head is in the SVG */}
            <div className="relative mb-6">
              <span
                className="block h-2.5 w-2.5 rounded-full"
                style={{
                  background: "var(--morr-fate-hi, #ff1a1a)",
                  animation: "morr-eye 6.5s ease-in-out infinite",
                  boxShadow: "0 0 15px rgba(255, 26, 26, 0.6), 0 0 30px rgba(122, 15, 30, 0.4)",
                }}
              />
            </div>

            <div className="text-center">
              <h4 className="text-lg font-black uppercase tracking-tight text-foreground/85">
                Monitor en Reposo
              </h4>
              <p className="mt-1 text-sm text-muted-foreground/70 max-w-[280px]">
                No hay tareas en ejecución en este momento.
              </p>
              <p className="mt-4 text-[11px] uppercase tracking-[0.22em] text-muted-foreground/40 animate-pulse">
                Watching.
              </p>
            </div>
          </div>
        </div>
      ) : error ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-10">
          <div className="text-sm text-muted-foreground/80">No hay señal de video activa</div>
          <div className="mt-2 text-[11px] uppercase tracking-[0.22em] text-muted-foreground/60">
            The Watcher is blind.
          </div>
        </div>
      ) : (
        <img
          src={`/api/queue/live-screenshot?t=${now}`}
          alt="Live Screencast"
          className="absolute inset-0 w-full h-full object-contain transition-opacity duration-500"
          onLoad={() => setLoading(false)}
          onError={() => {
            setError(true);
            setLoading(false);
          }}
          style={{ opacity: loading ? 0 : 1 }}
        />
      )}

      {/* Loading overlay */}
      {live && loading && !error && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-[rgba(0,0,0,0.25)]">
          <div className="h-10 w-10 rounded-full border border-[rgba(108,77,255,0.20)] border-t-[rgba(108,77,255,0.65)] animate-spin" />
        </div>
      )}
    </div>
  );
}