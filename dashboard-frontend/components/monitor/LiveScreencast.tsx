"use client";

import React, { useEffect, useState } from "react";
import { Monitor } from "lucide-react";
import { queueApi } from "@/lib/api";

interface LiveScreencastProps {
  live?: boolean;
}

export default function LiveScreencast({ live = false }: LiveScreencastProps) {
  const [viewerUrl, setViewerUrl] = useState("");
  const [viewerEnabled, setViewerEnabled] = useState(false);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const cfg = await queueApi.getLiveViewer();
        if (!mounted) {
          return;
        }
        setViewerEnabled(!!cfg.enabled);
        setViewerUrl(cfg.novnc_url || "");
        setError(!cfg.enabled || !cfg.novnc_url);
      } catch {
        if (mounted) {
          setViewerEnabled(false);
          setViewerUrl("");
          setError(true);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div
      className="relative overflow-hidden min-h-[500px] rounded morr-card morr-edge transition-all duration-500 bg-[#050608]"
      style={{
        background: "radial-gradient(circle at center, rgba(20,22,28,1) 0%, rgba(5,6,8,1) 100%)",
      }}
    >
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

      {!live ? (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <img
              src="/raven.webp"
              alt="Morrigan Logo"
              className="w-full max-w-[500px] opacity-[0.15] select-none transition-opacity duration-1000"
              style={{
                filter: "grayscale(1) brightness(1.2) contrast(1.1)",
                maskImage: "radial-gradient(circle, black 40%, transparent 90%)",
                WebkitMaskImage: "radial-gradient(circle, black 40%, transparent 90%)",
              }}
            />
          </div>

          <div className="relative z-10 flex flex-col items-center">
            <div className="text-center animate-pulse duration-[4000ms]">
              <h4 className="text-xl font-black uppercase tracking-tighter text-white/80 drop-shadow-[0_0_15px_rgba(255,255,255,0.1)]">
                Monitor en Reposo
              </h4>
              <p className="mt-1 text-sm text-white/30 font-medium tracking-wide">
                Esperando senales de ejecucion...
              </p>

              <div className="mt-8 flex flex-col items-center gap-3">
                <div className="h-[1px] w-24 bg-gradient-to-r from-transparent via-white/20 to-transparent" />
                <p className="text-[11px] uppercase tracking-[0.5em] text-[#ff0022]/60 font-bold">Watching</p>
              </div>
            </div>
          </div>
        </div>
      ) : loading ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <p className="text-sm text-white/40 tracking-widest uppercase">Connecting...</p>
        </div>
      ) : error || !viewerEnabled ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <p className="text-sm text-white/40 tracking-widest uppercase">Viewer Unavailable</p>
        </div>
      ) : (
        <iframe
          src={viewerUrl}
          title="Playwright noVNC Viewer"
          className="absolute inset-0 w-full h-full border-0 transition-opacity duration-300"
          allow="clipboard-read; clipboard-write"
          onLoad={() => {
            setLoading(false);
            setError(false);
          }}
          onError={() => setError(true)}
          style={{ opacity: loading ? 0.35 : 1, background: "#050608" }}
        />
      )}

      <div
        className="absolute inset-0 pointer-events-none opacity-[0.05]"
        style={{
          background:
            "linear-gradient(135deg, rgba(255,255,255,0.1) 0%, transparent 40%, transparent 60%, rgba(255,255,255,0.1) 100%)",
        }}
      />
    </div>
  );
}
