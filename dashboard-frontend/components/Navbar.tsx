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
  AlertCircle,
  FileText,
} from "lucide-react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { useAuth } from "@/lib/AuthContext";
import { isClientView } from "@/lib/permissions";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

type NavLink = {
  href: string;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  adminOnly: boolean;
};

export default function Navbar() {
  const pathname = usePathname();
  const { user, isAdmin, logout } = useAuth();
  const [scrolled, setScrolled] = useState(false);
  const [quickSearch, setQuickSearch] = useState("");

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 18);
    handleScroll();
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const navLinks: NavLink[] = [
    { href: "/", label: "Estado", icon: LayoutDashboard, adminOnly: false },
    { href: "/history", label: "Historial", icon: History, adminOnly: false },
    { href: "/gestion", label: "Gestion", icon: Settings, adminOnly: false },
    { href: "/incidents", label: "Incidencias", icon: AlertCircle, adminOnly: false },
    { href: "/control", label: "Control", icon: Terminal, adminOnly: true },
    { href: "/blacklist", label: "Bloqueos", icon: ShieldAlert, adminOnly: false },
    { href: "/documentos", label: "Documentos", icon: FileText, adminOnly: false },
  ]
    .filter((link) => !link.adminOnly || isAdmin)
    .filter((link) => !(isClientView && link.href === "/control"));

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
        <Link href="/" className="flex items-center gap-3 group">
          <div
            className={cn(
              "w-10 h-10 rounded border",
              "flex items-center justify-center",
              "bg-[rgba(17,19,26,0.80)] border-[rgba(255,255,255,0.06)]",
              "group-hover:border-[rgba(108,77,255,0.22)] transition-all duration-500"
            )}
          >
            <span className="text-[11px] font-black tracking-[0.25em] text-foreground/80">
              M
            </span>
          </div>

          <div className="hidden sm:block">
            <h1 className="text-[13px] font-black uppercase tracking-[0.14em] leading-none text-foreground/90">
              Morrigan
            </h1>
            <p className="text-xs text-muted-foreground/70 leading-none mt-1">
              Monitor and Control
            </p>
          </div>
        </Link>

        <div className="hidden lg:flex items-center gap-1 rounded border border-border/70 bg-[rgba(17,19,26,0.65)] p-0.5">
          {navLinks.map((link) => {
            const Icon = link.icon;
            const active = pathname === link.href;

            return (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "relative flex items-center gap-2",
                  "px-4 py-2 rounded-sm",
                  "text-[11px] font-black uppercase tracking-[0.15em]",
                  "transition-all duration-300",
                  active
                    ? "text-foreground bg-foreground/5 shadow-inner"
                    : "text-muted-foreground/60 hover:text-foreground hover:bg-foreground/5"
                )}
              >
                <Icon
                  size={14}
                  className={cn(
                    "transition-colors",
                    active
                      ? "text-foreground/90"
                      : "text-muted-foreground/50 group-hover:text-foreground/75"
                  )}
                />
                {link.label}
                {active && (
                  <span
                    className="absolute inset-x-2 -bottom-[1px] h-[0.5px]"
                    style={{
                      background: "linear-gradient(90deg, transparent, var(--morr-fate), transparent)",
                    }}
                  />
                )}
              </Link>
            );
          })}
        </div>

        <div className="flex items-center gap-4">
          <div className="relative hidden md:block group">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/70 group-focus-within:text-[rgba(108,77,255,0.75)] transition-colors"
              size={16}
            />
            <input
              type="text"
              placeholder="Buscar tramite..."
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

          <div className="flex items-center gap-3">
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

            <div className="flex items-center gap-2">
              <div
                className={cn(
                  "h-10 rounded-full",
                  "bg-[rgba(17,19,26,0.55)]",
                  "border border-border/70",
                  "flex items-center gap-2 px-3",
                  "hover:border-[rgba(108,77,255,0.22)] transition"
                )}
                aria-label="Usuario"
              >
                <User size={18} className="text-foreground/80" />
                <span className="text-[10px] uppercase tracking-[0.16em] font-black text-foreground/85">
                  {user?.username || "Usuario"}
                </span>
              </div>
              <button
                onClick={() => void logout()}
                className="text-[10px] uppercase tracking-[0.16em] font-black rounded-full border border-border/70 bg-[rgba(17,19,26,0.55)] px-3 py-2 text-foreground/80 hover:text-foreground hover:border-[rgba(108,77,255,0.22)] transition"
              >
                Salir
              </button>
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}
