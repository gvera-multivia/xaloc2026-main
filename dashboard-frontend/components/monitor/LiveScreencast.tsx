"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Monitor, Cpu, ChevronDown } from "lucide-react";
import { queueApi, controlApi } from "@/lib/api";

interface LiveScreencastProps {
  live?: boolean;
  onWorkerSelect?: (workerId: string) => void;
}

export default function LiveScreencast({ live = false, onWorkerSelect }: LiveScreencastProps) {
  const [viewerUrl, setViewerUrl] = useState("");
  const [viewerEnabled, setViewerEnabled] = useState(false);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [activeWorkers, setActiveWorkers] = useState<any[]>([]);
  const [selectedWorkerId, setSelectedWorkerId] = useState<string | null>(null);
  const [showWorkerSelector, setShowWorkerSelector] = useState(false);

  const fetchViewer = useCallback(async (workerId?: string) => {
    setLoading(true);
    try {
      const cfg = await queueApi.getLiveViewer(workerId || undefined);
      setViewerEnabled(!!cfg.enabled);
      setViewerUrl(cfg.novnc_url || "");
      setError(!cfg.enabled || !cfg.novnc_url);
    } catch {
      setViewerEnabled(false);
      setViewerUrl("");
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshWorkers = useCallback(async () => {
    try {
      const res = await controlApi.getActiveWorkers();
      setActiveWorkers(res.items || []);

      // Si no hay worker seleccionado y hay workers activos, seleccionar el primero por defecto
      if (!selectedWorkerId && res.items && res.items.length > 0) {
        const firstId = res.items[0].worker_id;
        setSelectedWorkerId(firstId);
        if (onWorkerSelect) {
          onWorkerSelect(firstId);
        }
      }
    } catch (e) {
      console.error("Fallo al obtener workers activos", e);
    }
  }, [selectedWorkerId]);

  useEffect(() => {
    refreshWorkers();
    const interval = setInterval(refreshWorkers, 5000);
    return () => clearInterval(interval);
  }, [refreshWorkers]);

  useEffect(() => {
    fetchViewer(selectedWorkerId || undefined);
  }, [selectedWorkerId, fetchViewer]);

  const handleWorkerSelect = (workerId: string) => {
    setSelectedWorkerId(workerId);
    setShowWorkerSelector(false);
    if (onWorkerSelect) {
      onWorkerSelect(workerId);
    }
  };

  return (
    <div
      className="relative overflow-hidden min-h-[500px] rounded morr-card morr-edge transition-all duration-500 bg-[#050608]"
      style={{
        background: "radial-gradient(circle at center, rgba(20,22,28,1) 0%, rgba(5,6,8,1) 100%)",
      }}
    >
      <div className="absolute top-5 left-5 z-20 flex flex-wrap gap-2">
        {live && (
          <div className="flex items-center gap-2 rounded-full border border-white/5 bg-black/40 backdrop-blur-md px-4 py-2">
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

        <div className="relative">
          <button
            onClick={() => setShowWorkerSelector(!showWorkerSelector)}
            className="flex items-center gap-2 rounded-full border border-white/5 bg-black/40 backdrop-blur-md px-4 py-2 text-[10px] font-bold uppercase tracking-[0.2em] text-white/80 hover:bg-black/60 transition-all"
          >
            <Cpu size={12} />
            {selectedWorkerId ? `Worker: ${selectedWorkerId.split('-').pop()}` : "Seleccionar Canal"}
            <ChevronDown size={12} className={`transition-transform ${showWorkerSelector ? 'rotate-180' : ''}`} />
          </button>

          {showWorkerSelector && activeWorkers.length > 0 && (
            <div className="absolute top-full left-0 mt-2 w-64 bg-black/80 backdrop-blur-xl border border-white/10 rounded-lg shadow-2xl z-50 py-2 animate-in fade-in slide-in-from-top-2 duration-200">
              <div className="px-3 py-1 mb-1 border-b border-white/5">
                <span className="text-[8px] font-black uppercase tracking-widest text-muted-foreground">Workers Conectados</span>
              </div>
              {activeWorkers.map((w) => (
                <button
                  key={w.worker_id}
                  onClick={() => handleWorkerSelect(w.worker_id)}
                  className={`w-full text-left px-4 py-2 text-[10px] font-bold uppercase tracking-widest transition-colors flex items-center justify-between ${
                    selectedWorkerId === w.worker_id ? 'bg-[color:var(--morr-fate)] text-white' : 'text-white/60 hover:bg-white/5'
                  }`}
                >
                  <span className="truncate">{w.worker_id.split('-').pop()}</span>
                  {w.current_job_id && (
                    <span className="ml-2 h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse shadow-[0_0_5px_rgba(34,197,94,0.5)]" title="Procesando tarea" />
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

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
