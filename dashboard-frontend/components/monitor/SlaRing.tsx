'use client';

import React from 'react';

interface SlaRingProps {
    progress: number;
    label: string;
    elapsed?: string;
}

export default function SlaRing({ progress, label, elapsed }: SlaRingProps) {
    const radius = 70;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (progress / 100) * circumference;

    return (
        <div className="relative flex items-center justify-center p-8 bg-card border border-border rounded-3xl shadow-xl overflow-hidden group">
            <div className="absolute inset-0 bg-primary/5 blur-3xl group-hover:bg-primary/10 transition-colors"></div>

            <svg className="w-48 h-48 transform -rotate-90 relative z-10">
                {/* Background track */}
                <circle
                    cx="96"
                    cy="96"
                    r={radius}
                    stroke="currentColor"
                    strokeWidth="12"
                    fill="transparent"
                    className="text-secondary/30"
                />
                {/* Progress fill */}
                <circle
                    cx="96"
                    cy="96"
                    r={radius}
                    stroke="currentColor"
                    strokeWidth="12"
                    strokeDasharray={circumference}
                    strokeDashoffset={offset}
                    strokeLinecap="round"
                    fill="transparent"
                    className="text-primary transition-all duration-1000 ease-out drop-shadow-[0_0_8px_rgba(var(--primary),0.5)]"
                />
            </svg>
            <div className="absolute flex flex-col items-center justify-center z-20">
                <span className="text-4xl font-black tracking-tighter">{progress}%</span>
                {elapsed && <span className="text-sm font-mono font-bold text-primary mt-1">{elapsed}</span>}
                <span className="text-[10px] text-muted-foreground uppercase font-black tracking-widest mt-2">{label}</span>
            </div>
        </div>
    );
}
