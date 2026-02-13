"use client";

import React from "react";
import { QueueItem } from "@/lib/types";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { Box, Clock, ChevronRight } from "lucide-react";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface QueueCardProps {
  item: QueueItem;
  index: number;
}

/**
 * MORRIGAN QUEUE CARD
 * - Surface: Raven/Obsidian
 * - Violet: only as edge transition + chevron hover
 * - Fate Crimson: “processing” + “high priority”
 * - No neon colors, no playful badges
 * - Looks native next to terminals: matte, restrained, precise
 */
export default function QueueCard({ item, index }: QueueCardProps) {
  const isProcessing = item.state === "processing";
  const priority = item.priority || (index < 2 ? "high" : "medium");

  const badgeClass =
    priority === "high"
      ? "border-[rgba(122,15,30,0.30)] bg-[rgba(122,15,30,0.10)] text-[rgba(255,255,255,0.92)]"
      : "border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.04)] text-muted-foreground/90";

  return (
    <div
      className={cn(
        "group relative rounded-xl border p-4 transition-all duration-300",
        "bg-[rgba(17,19,26,0.55)] border-[rgba(255,255,255,0.06)]",
        "hover:border-[rgba(108,77,255,0.22)] hover:bg-[rgba(17,19,26,0.62)]",
        isProcessing &&
          "border-[rgba(122,15,30,0.28)] bg-[rgba(122,15,30,0.06)]"
      )}
    >
      {/* Processing marker (quiet heat, not ping spam) */}
      {isProcessing && (
        <div className="absolute top-3 right-3">
          <span
            className="block h-2 w-2 rounded-full"
            style={{
              background: "var(--morr-fate)",
              boxShadow: "0 0 12px rgba(122,15,30,0.25)",
              animation: "morr-eye 6.5s ease-in-out infinite",
            }}
          />
        </div>
      )}

      <div className="flex items-start gap-3">
        {/* Icon tile */}
        <div
          className={cn(
            "h-10 w-10 rounded-lg border flex items-center justify-center transition-colors",
            "border-[rgba(255,255,255,0.06)] bg-[rgba(11,12,16,0.55)]",
            "group-hover:border-[rgba(108,77,255,0.20)]",
            isProcessing && "border-[rgba(122,15,30,0.20)] bg-[rgba(122,15,30,0.08)]"
          )}
        >
          <Box
            size={18}
            className={cn(
              "text-foreground/75",
              isProcessing && "text-[rgba(255,255,255,0.90)]"
            )}
          />
        </div>

        {/* Main */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <h4 className="text-sm font-black tracking-tight truncate text-foreground/95">
              #{item.resource_id}
            </h4>

            <span
              className={cn(
                "text-[10px] font-black uppercase tracking-[0.14em] px-2 py-1 rounded-md border",
                badgeClass
              )}
            >
              {priority}
            </span>
          </div>

          <p className="mt-1 text-xs text-muted-foreground/80 truncate">
            {item.site_id}
          </p>

          <div className="mt-3 flex items-center gap-3 text-[11px] text-muted-foreground/70">
            <span className="flex items-center gap-1">
              <Clock size={12} className="text-muted-foreground/70" />
              <span className="uppercase tracking-[0.12em]">{item.state}</span>
            </span>

            {item.protocol && (
              <span className="px-2 py-1 rounded-md border border-[rgba(255,255,255,0.06)] bg-[rgba(11,12,16,0.45)]">
                <span className="uppercase tracking-[0.12em]">Type</span>:{" "}
                {item.protocol}
              </span>
            )}
          </div>
        </div>

        {/* Chevron */}
        <div className="self-center">
          <ChevronRight
            size={16}
            className="text-muted-foreground/35 transition-colors group-hover:text-[rgba(108,77,255,0.80)]"
          />
        </div>
      </div>

      {/* Fate underline only when processing (signals “destiny in motion”) */}
      {isProcessing && <div className="morr-fate-underline" />}
    </div>
  );
}
