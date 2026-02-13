"use client";

import React, { useMemo } from "react";

interface SlaRingProps {
  progress: number;
  label: string;
  elapsed?: string;
}

/**
 * MORRIGAN SLA RING
 * - Surface: Raven/Obsidian (morr-card)
 * - Violet: only on edge transition (morr-edge) and subtle hover
 * - Fate Crimson: progress + key numeric emphasis (inevitable countdown)
 * - No neon glow, no big blur backgrounds
 */
export default function SlaRing({ progress, label, elapsed }: SlaRingProps) {
  const radius = 70;
  const circumference = useMemo(() => 2 * Math.PI * radius, [radius]);
  const clamped = Math.max(0, Math.min(100, progress));
  const offset = circumference - (clamped / 100) * circumference;

  // Morrigan: “quiet but addictive” = tight, controlled highlight
  const fateStroke = "rgba(122, 15, 30, 0.92)"; // var(--morr-fate) feel
  const trackStroke = "rgba(255,255,255,0.08)";
  const innerTick = "rgba(108,77,255,0.08)";

  return (
    <div className="relative morr-card morr-edge rounded-2xl overflow-hidden p-8">
      {/* Subtle inner surface split (violet only as a surface transition whisper) */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.35]"
        style={{
          background: `radial-gradient(600px 300px at 50% 10%,
            ${innerTick}, transparent 55%)`,
        }}
      />

      <div className="relative flex items-center justify-center">
        <svg className="w-48 h-48 -rotate-90">
          {/* Track */}
          <circle
            cx="96"
            cy="96"
            r={radius}
            stroke={trackStroke}
            strokeWidth="12"
            fill="transparent"
          />

          {/* Progress (FATE) */}
          <circle
            cx="96"
            cy="96"
            r={radius}
            stroke={fateStroke}
            strokeWidth="12"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            fill="transparent"
            style={{
              transition: "stroke-dashoffset 900ms ease-out",
              filter: "drop-shadow(0 0 10px rgba(122,15,30,0.18))",
            }}
          />
        </svg>

        {/* Center copy */}
        <div className="absolute flex flex-col items-center justify-center text-center">
          <span className="text-4xl font-black tracking-tight text-foreground">
            {clamped}%
          </span>

          {elapsed && (
            <span
              className="mt-1 text-sm font-mono font-black"
              style={{ color: "rgba(122, 15, 30, 0.92)" }}
            >
              {elapsed}
            </span>
          )}

          <span className="mt-3 text-[10px] uppercase font-black tracking-[0.22em] text-muted-foreground/80">
            {label}
          </span>
        </div>
      </div>

      {/* Thin fate underline at base (subtle, addictive cue) */}
      <div className="morr-fate-underline" />
    </div>
  );
}
