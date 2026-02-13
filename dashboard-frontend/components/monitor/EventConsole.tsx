'use client';

import React from 'react';
import { Terminal as TerminalIcon, Clock } from 'lucide-react';
import { EventLog } from '@/lib/types';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

interface EventConsoleProps {
    logs: EventLog[];
}

export default function EventConsole({ logs }: EventConsoleProps) {
    return (
        <div className="flex flex-col h-full morr-terminal rounded-xl overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2 bg-[rgba(17,19,26,0.35)] border-b border-border/70">
                <div className="flex items-center gap-2">
                    <TerminalIcon size={14} className="text-foreground/70" />
                    <span className="text-[10px] font-black uppercase tracking-[0.22em] text-foreground/85">
                        Consola de Eventos
                    </span>
                </div>
                {/* Minimal terminal buttons (subtle, non-playful) */}
                <div className="flex gap-1.5 opacity-30">
                    <div className="w-2 h-2 rounded-full bg-foreground/20"></div>
                    <div className="w-2 h-2 rounded-full bg-foreground/20"></div>
                    <div className="w-2 h-2 rounded-full bg-foreground/20"></div>
                </div>
            </div>

            <div className="flex-1 p-4 font-mono text-[11px] overflow-y-auto space-y-1.5 scrollbar-thin scrollbar-thumb-muted-foreground/20">
                {logs.length === 0 ? (
                    <div className="h-full flex items-center justify-center text-muted-foreground/30 italic uppercase tracking-widest text-[10px]">
                        Waiting for system signal...
                    </div>
                ) : (
                    logs.map((log, idx) => (
                        <div key={`${log.ts}-${idx}`} className="flex gap-3 group">
                            <span className="text-muted-foreground/40 whitespace-nowrap font-bold">
                                [{new Date(log.ts).toLocaleTimeString("es-ES")}]
                            </span>
                            <span
                                className={cn(
                                    "break-all tracking-tight",
                                    log.kind === "ok" && "text-foreground/90",
                                    log.kind === "warn" && "text-[rgba(255,200,80,0.85)]",
                                    log.kind === "error" && "text-[rgba(255,60,80,0.85)]",
                                    log.kind === "info" && "text-muted-foreground/80"
                                )}
                            >
                                <span className="opacity-30 mr-2 font-black">
                                    {log.kind === "ok"
                                        ? "::"
                                        : log.kind === "error"
                                            ? "!!"
                                            : log.kind === "warn"
                                                ? "??"
                                                : ">>"}
                                </span>
                                {log.msg}
                            </span>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}
