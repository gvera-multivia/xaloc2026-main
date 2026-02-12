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
        <div className="flex flex-col h-full bg-[#0D0D0D] border border-border rounded-xl overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-4 py-2 bg-secondary/30 border-b border-border">
                <div className="flex items-center gap-2">
                    <TerminalIcon size={14} className="text-primary" />
                    <span className="text-xs font-bold uppercase tracking-wider">Consola de Eventos</span>
                </div>
                <div className="flex gap-1.5">
                    <div className="w-2.5 h-2.5 rounded-full bg-red-500/50"></div>
                    <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/50"></div>
                    <div className="w-2.5 h-2.5 rounded-full bg-green-500/50"></div>
                </div>
            </div>

            <div className="flex-1 p-4 font-mono text-xs overflow-y-auto space-y-1 scrollbar-thin scrollbar-thumb-muted-foreground/20">
                {logs.length === 0 ? (
                    <div className="h-full flex items-center justify-center text-muted-foreground/30 italic">
                        Esperando eventos del sistema...
                    </div>
                ) : (
                    logs.map((log, idx) => (
                        <div key={`${log.ts}-${idx}`} className="flex gap-3 group">
                            <span className="text-muted-foreground/50 whitespace-nowrap">
                                [{new Date(log.ts).toLocaleTimeString('es-ES')}]
                            </span>
                            <span className={cn(
                                "break-all",
                                log.kind === 'ok' && "text-green-400",
                                log.kind === 'warn' && "text-yellow-400",
                                log.kind === 'error' && "text-red-400",
                                log.kind === 'info' && "text-blue-400"
                            )}>
                                <span className="opacity-50 mr-2">
                                    {log.kind === 'ok' ? '✓' : log.kind === 'error' ? '!' : log.kind === 'warn' ? '?' : 'i'}
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
