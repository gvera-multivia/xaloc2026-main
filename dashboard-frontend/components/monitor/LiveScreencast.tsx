"use client";

import React, { useEffect, useState } from "react";
import { Monitor, RefreshCw } from "lucide-react";

interface LiveScreencastProps {
  live?: boolean;
}

/**
 * MORRIGAN LiveScreencast
 * - Idle state: uses 'raven.webp' as a ghostly silhouette.
 * - Crimson eye positioned to overlay the logo's eye socket.
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
        background: "linear-gradient(180deg, rgba(12,14,18,0.6) 0%, rgba(5,6,8,0.9) 100%)",
      }}
    >
      {/* --- LIVE HUD --- */}
      {live && (
        <div className="absolute top-5 left-5 z-20 flex items-center gap-2 rounded-full border border-white/5 bg-black/40 backdrop-blur-md px-4 py-2">
          <span
            className="h-2 w-2 rounded-full animate-pulse"
            style={{
              background: "var(--morr-fate, #7a0f1e)",
              boxShadow: "0 0 8px #7a0f1e",
            }}
          />
          <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-white/80 flex items-center gap-2">
            <Monitor size={12} />
            LIVE
          </span>
        </div>
      )}

      {/* --- CONTENT --- */}
      {!live ? (
        <div className="absolute inset-0 flex items-center justify-center">
          {/* Raven Logo Shadow Presence */}
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <img 
              src="/raven.webp" 
              alt="Morrigan Logo" 
              className="w-full max-w-[450px] opacity-[0.07] select-none"
              style={{
                filter: "grayscale(1) brightness(0.8) contrast(1.2)",
                maskImage: "radial-gradient(circle, black 30%, transparent 80%)",
                WebkitMaskImage: "radial-gradient(circle, black 30%, transparent 80%)",
              }}
            />
          </div>

          {/* The Eye & Typography */}
          <div className="relative z-10 flex flex-col items-center">
            {/* Crimson Eye - Aligned with the 'eye' area of your raven.webp */}
            <div className="relative mb-6 mr-[-28px] mt-[-10px]"> 
              <span
                className="block h-2 w-2 rounded-full"
                style={{
                  background: "#ff0022",
                  animation: "morr-eye 5s ease-in-out infinite",
                  boxShadow: "0 0 12px rgba(255, 0, 34, 0.7), 0 0 25px rgba(255, 0, 34, 0.3)",
                }}
              />
              {/* Inner focus glow */}
              <span className="absolute inset-0 rounded-full bg-white/20 blur-[1px]" />
            </div>

            <div className="text-center">
              <h4 className="text-lg font-black uppercase tracking-tighter text-white/90">
                Monitor en Reposo
              </h4>
              <p className="mt-1 text-sm text-white/40 font-medium">
                No hay tareas en ejecución.
              </p>
              <div className="mt-6 h-[1px] w-12 bg-gradient-to-r from-transparent via-white/10 to-transparent" />
              <p className="mt-4 text-[10px] uppercase tracking-[0.3em] text-white/20">
                Watching.
              </p>
            </div>
          </div>
        </div>
      ) : error ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <p className="text-sm text-white/40 tracking-widest uppercase">No Signal</p>
        </div>
      ) : (
        <img
          src={`/api/queue/live-screenshot?t=${now}`}
          alt="Live Stream"
          className="absolute inset-0 w-full h-full object-contain transition-opacity duration-700"
          onLoad={() => setLoading(false)}
          style={{ opacity: loading ? 0 : 1 }}
        />
      )}

      {/* Glass Reflection Overlay */}
      <div 
        className="absolute inset-0 pointer-events-none opacity-[0.03]"
        style={{
          background: "linear-gradient(135deg, white 0%, transparent 40%, transparent 60%, white 100%)"
        }}
      />
    </div>
  );
}