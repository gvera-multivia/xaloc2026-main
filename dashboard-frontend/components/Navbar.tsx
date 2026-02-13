"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Settings,
  History,
  ShieldAlert,
  Search,
  User,
  Terminal,
  LayoutDashboard,
} from "lucide-react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * MORRIGAN NAVBAR
 * - Surfaces: Raven/Obsidian (matte)
 * - Violet: only as transition (hover/focus/edge), never as big filled pills
 * - Fate Crimson: only for â€œactiveâ€ marker (underline / thin rail), not full backgrounds
 * - Terminal harmony: restrained chips, no neon greens
 */
export default function Navbar() {
  const pathname = usePathname();
  const [scrolled, setScrolled] = useState(false);
  const [quickSearch, setQuickSearch] = useState("");

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 18);
    handleScroll();
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const navLinks = [
    { href: "/", label: "Estado", icon: LayoutDashboard },
    { href: "/control", label: "Control", icon: Terminal },
    { href: "/admin", label: "GestiÃ³n", icon: Settings },
    { href: "/history", label: "Historial", icon: History },
    { href: "/blacklist", label: "Bloqueos", icon: ShieldAlert },
  ];

  return (
    <nav
      className={cn(
        "fixed top-0 left-0 right-0 z-50",
        "transition-all duration-300",
        "border-b",
        scrolled
          ? "bg-[rgba(11,12,16,0.62)] backdrop-blur-md border-border/70 py-2"
          : "bg-transparent border-transparent py-4"
      )}
    >
      <div className="container mx-auto px-4 flex items-center justify-between">
        {/* Brand */}
        <Link href="/" className="flex items-center gap-3 group">
          {/* Replace 'M' with your raven side logo later; keep as sigil placeholder */}
          <div
            className={cn(
              "w-10 h-10 rounded-xl border",
              "flex items-center justify-center",
              "bg-[rgba(17,19,26,0.70)] border-[rgba(255,255,255,0.08)]",
              "group-hover:border-[rgba(108,77,255,0.22)] transition"
            )}
          >
            <span className="text-[11px] font-black tracking-[0.18em] text-foreground/90">
              M
            </span>
          </div>

          <div className="hidden sm:block">
            <h1 className="text-[13px] font-black uppercase tracking-[0.14em] leading-none text-foreground/90">
              Morrigan
            </h1>
            <p className="text-xs text-muted-foreground/70 leading-none mt-1">
              Monitor & Control
            </p>
          </div>
        </Link>

        {/* Nav links (desktop) */}
        <div className="hidden lg:flex items-center gap-1 rounded-xl border border-border/70 bg-[rgba(17,19,26,0.55)] p-1">
          {navLinks.map((link) => {
            const Icon = link.icon;
            const isActive = pathname === link.href;

            return (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "relative flex items-center gap-2",
                  "px-4 py-2 rounded-lg",
                  "text-[12px] font-black uppercase tracking-[0.12em]",
                  "transition",
                  isActive
                    ? "text-foreground"
                    : "text-muted-foreground/80 hover:text-foreground hover:bg-[rgba(255,255,255,0.04)]"
                )}
              >
                <Icon
                  size={16}
                  className={cn(
                    "transition-colors",
                    isActive
                      ? "text-foreground/90"
                      : "text-muted-foreground/75 group-hover:text-foreground/80"
                  )}
                />
                {link.label}

                {/* Active = Fate underline (thin, addictive, not loud) */}
                {isActive && (
                  <span
                    className="absolute left-4 right-4 -bottom-[2px] h-[1px]"
                    style={{
                      background:
                        "linear-gradient(90deg, transparent, rgba(122,15,30,0.80), transparent)",
                    }}
                  />
                )}
              </Link>
            );
          })}
        </div>

        {/* Right controls */}
        <div className="flex items-center gap-4">
          {/* Quick search */}
          <div className="relative hidden md:block group">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/70 group-focus-within:text-[rgba(108,77,255,0.75)] transition-colors"
              size={16}
            />
            <input
              type="text"
              placeholder="Buscar trÃ¡miteâ€¦"
              value={quickSearch}
              onChange={(e) => setQuickSearch(e.target.value)}
              className={cn(
                "morr-focus",
                "bg-[rgba(17,19,26,0.55)]",
                "border border-[rgba(255,255,255,0.08)]",
                "focus:border-[rgba(108,77,255,0.30)]",
                "outline-none rounded-full",
                "pl-10 pr-4 py-2",
                "text-sm w-48 lg:w-64",
                "transition"
              )}
            />
          </div>

          {/* Status chip + user */}
          <div className="flex items-center gap-3">
            {/* Worker status (terminal-like, not neon) */}
            <div className="flex items-center gap-2 rounded-full border border-border/70 bg-[rgba(17,19,26,0.55)] px-3 py-2">
              <span
                className="w-2 h-2 rounded-full"
                style={{
                  background: "rgba(108,77,255,0.85)",
                  boxShadow: "0 0 10px rgba(108,77,255,0.18)",
                }}
              />
              <span className="text-[10px] font-black uppercase tracking-[0.20em] text-foreground/85">
                Worker Online
              </span>
            </div>

            <button
              className={cn(
                "morr-focus",
                "w-10 h-10 rounded-full",
                "bg-[rgba(17,19,26,0.55)]",
                "border border-border/70",
                "flex items-center justify-center",
                "hover:border-[rgba(108,77,255,0.22)] transition"
              )}
              aria-label="Usuario"
            >
              <User size={18} className="text-foreground/80" />
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}

