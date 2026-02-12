'use client';

import React from 'react';
import { QueueItem } from '@/lib/types';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { Box, Clock, ChevronRight } from 'lucide-react';

function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

interface QueueCardProps {
    item: QueueItem;
    index: number;
}

export default function QueueCard({ item, index }: QueueCardProps) {
    const isProcessing = item.state === 'processing';
    const priority = item.priority || (index < 2 ? 'high' : 'medium');

    return (
        <div className={cn(
            "group relative p-4 rounded-xl border transition-all duration-300 overflow-hidden",
            isProcessing
                ? "bg-primary/5 border-primary/50 shadow-[0_0_20px_rgba(var(--primary),0.1)]"
                : "bg-secondary/20 border-border hover:border-muted-foreground/50"
        )}>
            {isProcessing && (
                <div className="absolute top-0 right-0 p-2">
                    <div className="w-2 h-2 bg-primary rounded-full animate-ping"></div>
                </div>
            )}

            <div className="flex items-start gap-3">
                <div className={cn(
                    "w-10 h-10 rounded-lg flex items-center justify-center transition-colors",
                    isProcessing ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground group-hover:bg-secondary/50"
                )}>
                    <Box size={20} />
                </div>

                <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                        <h4 className="text-sm font-bold truncate">#{item.resource_id}</h4>
                        <span className={cn(
                            "text-[10px] font-bold px-1.5 py-0.5 rounded uppercase tracking-tighter",
                            priority === 'high' ? "text-red-400 bg-red-400/10" : "text-yellow-400 bg-yellow-400/10"
                        )}>
                            {priority}
                        </span>
                    </div>

                    <p className="text-xs text-muted-foreground truncate mb-2">{item.site_id}</p>

                    <div className="flex items-center gap-3 text-[10px] text-muted-foreground/60">
                        <span className="flex items-center gap-1">
                            <Clock size={10} />
                            {item.state}
                        </span>
                        {item.protocol && (
                            <span className="px-1.5 py-0.5 rounded bg-secondary/50 border border-border/30">
                                Type: {item.protocol}
                            </span>
                        )}
                    </div>
                </div>

                <div className="self-center">
                    <ChevronRight size={16} className="text-muted-foreground/30 group-hover:text-primary transition-colors" />
                </div>
            </div>
        </div>
    );
}
