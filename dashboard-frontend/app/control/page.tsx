'use client';

import React, { useState, useEffect, useRef } from 'react';
import {
    Play,
    Square,
    RotateCcw,
    Cpu,
    Database
} from 'lucide-react';
import { controlApi } from '@/lib/api';
import { sileo } from 'sileo';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

export default function ControlPage() {
    const STATUS_REFRESH_MS = 4000;
    const LOGS_REFRESH_MS = 15000;

    const [status, setStatus] = useState<{ worker: string; brain: string }>({ worker: 'stopped', brain: 'stopped' });
    const [logs, setLogs] = useState<{ worker: string[]; brain: string[] }>({ worker: [], brain: [] });
    const [busy, setBusy] = useState<string | null>(null);
    const [autoScroll, setAutoScroll] = useState(true);

    const workerLogRef = useRef<HTMLDivElement>(null);
    const brainLogRef = useRef<HTMLDivElement>(null);
    const statusRequestRef = useRef(false);
    const logsRequestRef = useRef(false);

    const refreshStatus = async () => {
        if (statusRequestRef.current) return;
        statusRequestRef.current = true;
        try {
            const statusRes = await controlApi.getStatus();
            const nextStatus = statusRes?.status ?? statusRes ?? {};
            setStatus({
                worker: String(nextStatus.worker || 'stopped').toLowerCase(),
                brain: String(nextStatus.brain || 'stopped').toLowerCase(),
            });
        } catch {
            sileo.error({ title: 'Error de conexion', description: 'No se pudo consultar el estado de los procesos.' });
        } finally {
            statusRequestRef.current = false;
        }
    };

    const refreshLogs = async () => {
        if (logsRequestRef.current) return;
        logsRequestRef.current = true;
        try {
            const [workerLogs, brainLogs] = await Promise.all([
                controlApi.getLogs('worker', 100),
                controlApi.getLogs('brain', 100),
            ]);
            setLogs({
                worker: workerLogs.stdout || [],
                brain: brainLogs.stdout || [],
            });
        } catch {
            sileo.error({ title: 'Error de conexion', description: 'No se pudieron actualizar los logs.' });
        } finally {
            logsRequestRef.current = false;
        }
    };

    useEffect(() => {
        void refreshStatus();
        void refreshLogs();

        const statusIntervalId = setInterval(() => {
            void refreshStatus();
        }, STATUS_REFRESH_MS);
        const logsIntervalId = setInterval(() => {
            void refreshLogs();
        }, LOGS_REFRESH_MS);

        return () => {
            clearInterval(statusIntervalId);
            clearInterval(logsIntervalId);
        };
    }, []);

    useEffect(() => {
        if (!autoScroll) return;
        if (workerLogRef.current) workerLogRef.current.scrollTop = workerLogRef.current.scrollHeight;
        if (brainLogRef.current) brainLogRef.current.scrollTop = brainLogRef.current.scrollHeight;

    }, [logs, autoScroll]);

    const handleControl = async (name: 'worker' | 'brain', action: 'start' | 'stop' | 'restart') => {
        setBusy(`${name}-${action}`);
        try {
            if (action === 'start') await controlApi.start(name);
            else if (action === 'stop') await controlApi.stop(name);
            else if (action === 'restart') await controlApi.restart(name);
            sileo.success({ title: `Servicio ${name}`, description: `Accion [${action}] ejecutada correctamente.` });
            await Promise.all([refreshStatus(), refreshLogs()]);
        } catch {
            sileo.error({ title: 'Error de control', description: `No se pudo ${action} el servicio ${name}.` });
        } finally {
            setBusy(null);
        }
    };

    const renderProcessCard = (name: 'worker' | 'brain', logRef: React.RefObject<HTMLDivElement | null>) => {
        const isRunning = status[name] === 'running';
        const Icon = name === 'worker' ? Cpu : Database;
        const processLogs = logs[name];
        const readOnly = false;

        return (
            <div className="flex flex-col h-full bg-card border border-border rounded-3xl overflow-hidden shadow-xl">
                <div className="p-5 border-b border-border flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className={cn(
                            "w-10 h-10 rounded-xl flex items-center justify-center transition-colors",
                            isRunning ? "bg-primary text-primary-foreground shadow-lg shadow-primary/20" : "bg-secondary text-muted-foreground"
                        )}>
                            <Icon size={20} />
                        </div>
                        <div>
                            <h3 className="font-bold capitalize">{name} Service</h3>
                            <div className="flex items-center gap-1.5">
                                <span className={cn("w-2 h-2 rounded-full", isRunning ? "bg-green-500 animate-pulse" : "bg-muted-foreground/30")}></span>
                                <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">{status[name]}</span>
                            </div>
                        </div>
                    </div>

                    <div className="flex items-center gap-2">
                        {!readOnly && !isRunning ? (
                            <button
                                onClick={() => handleControl(name, 'start')}
                                disabled={!!busy}
                                className="w-10 h-10 flex items-center justify-center bg-green-500 text-white rounded-xl hover:scale-105 active:scale-95 transition-all shadow-lg shadow-green-500/20 disabled:opacity-50"
                            >
                                <Play size={18} fill="currentColor" />
                            </button>
                        ) : !readOnly ? (
                            <>
                                <button
                                    onClick={() => handleControl(name, 'restart')}
                                    disabled={!!busy}
                                    className="w-10 h-10 flex items-center justify-center bg-secondary text-foreground rounded-xl hover:bg-primary/20 hover:text-primary transition-all active:scale-95 border border-border disabled:opacity-50"
                                >
                                    <RotateCcw size={18} />
                                </button>
                                <button
                                    onClick={() => handleControl(name, 'stop')}
                                    disabled={!!busy}
                                    className="w-10 h-10 flex items-center justify-center bg-destructive text-destructive-foreground rounded-xl hover:scale-105 active:scale-95 transition-all shadow-lg shadow-destructive/20 disabled:opacity-50"
                                >
                                    <Square size={18} fill="currentColor" />
                                </button>
                            </>
                        ) : (
                            <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">read-only</span>
                        )}
                    </div>
                </div>

                <div className="flex-1 bg-[#0D0D0D] p-4 text-[11px] font-mono overflow-y-auto scrollbar-thin scrollbar-thumb-muted-foreground/20" ref={logRef}>
                    {processLogs.length === 0 ? (
                        <p className="text-muted-foreground/30 italic h-full flex items-center justify-center">No logs available for {name}...</p>
                    ) : (
                        processLogs.map((line, i) => (
                            <div key={i} className="flex gap-4 group">
                                <span className="text-muted-foreground/30 select-none text-right w-6">{i + 1}</span>
                                <span className={cn(
                                    "break-all",
                                    line.includes('ERROR') || line.includes('CRITICAL') ? "text-red-400" :
                                        line.includes('WARNING') ? "text-yellow-400" : "text-zinc-400"
                                )}>{line}</span>
                            </div>
                        ))
                    )}
                </div>

                <div className="p-3 bg-secondary/30 border-t border-border flex items-center justify-between">
                    <label className="flex items-center gap-2 cursor-pointer group">
                        <input
                            type="checkbox"
                            checked={autoScroll}
                            onChange={e => setAutoScroll(e.target.checked)}
                            className="w-4 h-4 rounded border-border bg-background text-primary focus:ring-primary"
                        />
                        <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground group-hover:text-foreground transition-colors">Auto-scroll</span>
                    </label>
                    <div className="flex gap-4">
                        <div className="flex items-center gap-1">
                            <span className="text-[9px] font-bold text-muted-foreground/50 uppercase">Buffer:</span>
                            <span className="text-[9px] font-bold text-foreground">{processLogs.length} lines</span>
                        </div>
                    </div>
                </div>
            </div>
        );
    };

    return (
        <div className="h-[calc(100vh-10rem)] max-h-[800px] flex flex-col gap-6 animate-in slide-in-from-right-4 duration-700">
            <div className="flex items-end justify-between">
                <div>
                    <h2 className="text-3xl font-black tracking-tighter">Control de Procesos</h2>
                    <p className="text-muted-foreground">Orquestacion de servicios y depuracion en tiempo real.</p>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 flex-1 min-h-0">
                {renderProcessCard('worker', workerLogRef)}
                {renderProcessCard('brain', brainLogRef)}
            </div>


        </div>
    );
}
