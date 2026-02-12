'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
    Activity,
    Settings,
    History,
    ShieldAlert,
    Search,
    User,
    Terminal,
    LayoutDashboard,
    ArrowUpCircle
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

export default function Navbar() {
    const pathname = usePathname();
    const [scrolled, setScrolled] = useState(false);
    const [quickSearch, setQuickSearch] = useState('');

    useEffect(() => {
        const handleScroll = () => setScrolled(window.scrollY > 20);
        window.addEventListener('scroll', handleScroll);
        return () => window.removeEventListener('scroll', handleScroll);
    }, []);

    const navLinks = [
        { href: '/', label: 'Estado', icon: LayoutDashboard },
        { href: '/control', label: 'Control', icon: Terminal },
        { href: '/admin', label: 'Gestión', icon: Settings },
        { href: '/history', label: 'Historial', icon: History },
        { href: '/blacklist', label: 'Bloqueos', icon: ShieldAlert },
        { href: '/updates', label: 'Actualizar', icon: ArrowUpCircle },
    ];

    return (
        <nav className={cn(
            "fixed top-0 left-0 right-0 z-50 transition-all duration-300 border-b",
            scrolled ? "bg-background/80 backdrop-blur-md py-2 border-border" : "bg-transparent py-4 border-transparent"
        )}>
            <div className="container mx-auto px-4 flex items-center justify-between">
                <Link href="/" className="flex items-center gap-2 group">
                    <div className="w-10 h-10 bg-primary rounded-xl flex items-center justify-center text-primary-foreground font-bold text-xl group-hover:scale-105 transition-transform">
                        XA
                    </div>
                    <div className="hidden sm:block">
                        <h1 className="text-lg font-bold leading-none">Xaloc Console</h1>
                        <p className="text-xs text-muted-foreground">Monitoreo y control</p>
                    </div>
                </Link>

                <div className="hidden lg:flex items-center gap-1 bg-secondary/50 p-1 rounded-lg">
                    {navLinks.map((link) => {
                        const Icon = link.icon;
                        const isActive = pathname === link.href;
                        return (
                            <Link
                                key={link.href}
                                href={link.href}
                                className={cn(
                                    "flex items-center gap-2 px-4 py-2 rounded-md transition-all text-sm font-medium",
                                    isActive
                                        ? "bg-primary text-primary-foreground shadow-lg"
                                        : "text-muted-foreground hover:text-foreground hover:bg-secondary"
                                )}
                            >
                                <Icon size={16} />
                                {link.label}
                            </Link>
                        );
                    })}
                </div>

                <div className="flex items-center gap-4">
                    <div className="relative hidden md:block group">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground group-focus-within:text-primary transition-colors" size={16} />
                        <input
                            type="text"
                            placeholder="Buscar tramite..."
                            value={quickSearch}
                            onChange={(e) => setQuickSearch(e.target.value)}
                            className="bg-secondary/50 border border-transparent focus:border-primary/50 focus:bg-background outline-none rounded-full pl-10 pr-4 py-2 text-sm w-48 lg:w-64 transition-all"
                        />
                    </div>

                    <div className="flex items-center gap-3">
                        <div className="flex items-center gap-2 bg-secondary/50 px-3 py-1.5 rounded-full border border-border/50">
                            <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
                            <span className="text-[10px] font-bold uppercase tracking-wider">Worker ON</span>
                        </div>

                        <button className="w-10 h-10 rounded-full bg-secondary flex items-center justify-center hover:bg-primary/20 transition-colors border border-border">
                            <User size={20} />
                        </button>
                    </div>
                </div>
            </div>
        </nav>
    );
}
