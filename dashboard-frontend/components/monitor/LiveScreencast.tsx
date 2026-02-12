'use client';

import React, { useState, useEffect } from 'react';
import { Monitor, RefreshCw, AlertCircle } from 'lucide-react';

interface LiveScreencastProps {
    live?: boolean;
}

export default function LiveScreencast({ live = false }: LiveScreencastProps) {
    const [now, setNow] = useState(Date.now());
    const [error, setError] = useState(false);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!live) return;
        const timer = setInterval(() => {
            setNow(Date.now());
        }, 5000);
        return () => clearInterval(timer);
    }, [live]);

    return (
        <div className="relative group rounded-3xl overflow-hidden border border-border bg-[#050505] min-h-[500px] flex items-center justify-center shadow-2xl transition-all duration-500">
            {live && (
                <div className="absolute top-6 left-6 z-10 flex items-center gap-2 bg-background/60 backdrop-blur-md px-4 py-2 rounded-full border border-border/50">
                    <div className="w-2.5 h-2.5 bg-red-500 rounded-full animate-pulse shadow-[0_0_8px_rgba(239,68,68,0.5)]"></div>
                    <span className="text-[10px] font-black uppercase tracking-widest flex items-center gap-2">
                        <Monitor size={14} className="text-red-500" />
                        Transmisión en Directo
                    </span>
                </div>
            )}

            {live && (
                <div className="absolute top-6 right-6 z-10 flex gap-2">
                    <button
                        onClick={() => { setNow(Date.now()); setLoading(true); setError(false); }}
                        className="p-2 rounded-xl bg-background/60 backdrop-blur-md border border-border/50 hover:bg-primary/20 transition-all active:scale-95"
                    >
                        <RefreshCw size={16} className={loading && !error ? "animate-spin text-primary" : "text-primary"} />
                    </button>
                </div>
            )}

            {!live ? (
                <div className="flex flex-col items-center gap-4 text-center animate-in fade-in zoom-in duration-1000">
                    <div className="w-20 h-20 rounded-full bg-secondary/20 flex items-center justify-center mb-2">
                        <AlertCircle size={40} className="text-muted-foreground/20" />
                    </div>
                    <div>
                        <h4 className="text-xl font-bold tracking-tight text-muted-foreground">Monitor en Reposo</h4>
                        <p className="text-sm text-muted-foreground/50 max-w-[200px]">No hay tareas en ejecución en este momento.</p>
                    </div>
                </div>
            ) : error ? (
                <div className="flex flex-col items-center gap-3 text-muted-foreground">
                    <AlertCircle size={48} className="opacity-20" />
                    <p className="text-sm">No hay señal de video activa</p>
                </div>
            ) : (
                <img
                    src={`/api/queue/live-screenshot?t=${now}`}
                    alt="Live Screencast"
                    className="w-full h-full object-contain transition-all duration-700"
                    onLoad={() => setLoading(false)}
                    onError={() => { setError(true); setLoading(false); }}
                    style={{
                        opacity: loading ? 0 : 1,
                        filter: loading ? 'blur(10px)' : 'none'
                    }}
                />
            )}

            {live && loading && !error && (
                <div className="absolute inset-0 flex items-center justify-center bg-secondary/5 transition-opacity">
                    <div className="w-10 h-10 border-2 border-primary/20 border-t-primary rounded-full animate-spin"></div>
                </div>
            )}
        </div>
    );
}
