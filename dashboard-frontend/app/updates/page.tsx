'use client';

import React, { useState, useEffect } from 'react';
import {
    RefreshCw,
    Download,
    AlertCircle,
    CheckCircle2,
    Rocket,
    ShieldCheck,
    Zap,
    RotateCcw
} from 'lucide-react';
import { controlApi } from '@/lib/api';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

export default function UpdatesPage() {
    const [updateStatus, setUpdateStatus] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [checking, setChecking] = useState(false);
    const [updating, setUpdating] = useState(false);
    const [error, setError] = useState('');
    const [restartStatus, setRestartStatus] = useState<any>(null);

    const fetchStatus = async () => {
        try {
            const [uStatus, rStatus] = await Promise.all([
                controlApi.getUpdateStatus(),
                controlApi.getRestartStatus()
            ]);
            setUpdateStatus(uStatus);
            setRestartStatus(rStatus);
            setError('');
        } catch (e) {
            setError('Error al obtener el estado de actualizaciones.');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchStatus();
        const interval = setInterval(fetchStatus, 5000);
        return () => clearInterval(interval);
    }, []);

    const handleCheck = async () => {
        setChecking(true);
        try {
            const result = await controlApi.checkUpdates();
            setUpdateStatus(result);
            if (!result.available) {
                // Just for visual feedback if not already known
            }
        } catch (e: any) {
            setError(e.message || 'Error al comprobar actualizaciones.');
        } finally {
            setChecking(false);
        }
    };

    const handleUpdate = async () => {
        if (!confirm('¿Estás seguro de que quieres iniciar la actualización? El sistema podría reiniciarse.')) return;
        setUpdating(true);
        try {
            await controlApi.runUpdate();
            await fetchStatus();
        } catch (e: any) {
            setError(e.message || 'Error al ejecutar la actualización.');
        } finally {
            setUpdating(false);
        }
    };

    const handleRestart = async () => {
        if (!confirm('¿Reiniciar el dashboard ahora?')) return;
        try {
            await controlApi.restartDashboard(1.0);
            alert('Reinicio programado. La página se recargará en unos segundos.');
            setTimeout(() => window.location.reload(), 3000);
        } catch (e: any) {
            setError(e.message || 'Error al programar el reinicio.');
        }
    };

    return (
        <div className="space-y-10 animate-in fade-in slide-in-from-top-4 duration-700">
            <div>
                <h2 className="text-3xl font-black tracking-tighter">Gestión de Actualizaciones</h2>
                <p className="text-muted-foreground">Mantén el sistema Xaloc Console al día con las últimas mejoras y parches.</p>
            </div>

            {error && (
                <div className="bg-destructive/10 border border-destructive/50 text-destructive px-4 py-3 rounded-xl flex items-center gap-3">
                    <AlertCircle size={18} />
                    <p className="text-sm font-medium">{error}</p>
                </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                {/* Update Card */}
                <div className="bg-card border border-border rounded-3xl p-8 shadow-xl flex flex-col gap-6">
                    <div className="flex items-center gap-4">
                        <div className="w-14 h-14 bg-primary/10 rounded-2xl flex items-center justify-center text-primary shadow-inner">
                            <Rocket size={28} />
                        </div>
                        <div>
                            <h3 className="text-xl font-bold">Actualización de Software</h3>
                            <p className="text-sm text-muted-foreground">Versión actual: <span className="text-foreground font-mono">v2.0.0</span></p>
                        </div>
                    </div>

                    <div className="flex-1 space-y-4">
                        <div className="bg-secondary/30 rounded-2xl p-6 border border-border/50">
                            {loading ? (
                                <div className="flex items-center gap-3 text-muted-foreground italic text-sm">
                                    <RefreshCw size={16} className="animate-spin" />
                                    Obteniendo estado...
                                </div>
                            ) : updateStatus?.available ? (
                                <div className="space-y-3">
                                    <div className="flex items-center gap-2 text-green-400">
                                        <Zap size={18} />
                                        <span className="font-bold">¡Nueva versión disponible!</span>
                                    </div>
                                    <p className="text-sm leading-relaxed">Se han detectado cambios en el repositorio principal. Se recomienda actualizar para obtener la mejor experiencia.</p>
                                </div>
                            ) : (
                                <div className="flex items-center gap-2 text-muted-foreground">
                                    <CheckCircle2 size={18} className="text-green-500" />
                                    <span className="text-sm font-medium">El sistema está actualizado.</span>
                                </div>
                            )}
                        </div>

                        {updateStatus?.in_progress && (
                            <div className="p-4 bg-primary/10 border border-primary/20 rounded-2xl flex items-center gap-4 animate-pulse">
                                <RefreshCw size={20} className="animate-spin text-primary" />
                                <div>
                                    <p className="text-sm font-bold text-primary">Actualización en curso...</p>
                                    <p className="text-[10px] uppercase tracking-widest text-primary/70">No cierres esta pestaña</p>
                                </div>
                            </div>
                        )}
                    </div>

                    <div className="flex gap-3">
                        <button
                            onClick={handleCheck}
                            disabled={checking || updating || updateStatus?.in_progress}
                            className="flex-1 px-6 py-3 bg-secondary text-foreground rounded-2xl text-xs font-bold hover:bg-secondary/80 transition-all flex items-center justify-center gap-2 active:scale-95 disabled:opacity-50"
                        >
                            <RefreshCw size={14} className={checking ? "animate-spin" : ""} />
                            Comprobar ahora
                        </button>
                        <button
                            onClick={handleUpdate}
                            disabled={!updateStatus?.available || updating || updateStatus?.in_progress}
                            className="flex-1 px-6 py-3 bg-primary text-primary-foreground rounded-2xl text-xs font-bold shadow-lg shadow-primary/20 hover:scale-105 transition-all flex items-center justify-center gap-2 active:scale-95 disabled:opacity-50"
                        >
                            <Download size={14} />
                            Actualizar Sistema
                        </button>
                    </div>
                </div>

                {/* System Maintenance Card */}
                <div className="bg-card border border-border rounded-3xl p-8 shadow-xl flex flex-col gap-6">
                    <div className="flex items-center gap-4">
                        <div className="w-14 h-14 bg-blue-400/10 rounded-2xl flex items-center justify-center text-blue-400 shadow-inner">
                            <ShieldCheck size={28} />
                        </div>
                        <div>
                            <h3 className="text-xl font-bold">Mantenimiento Global</h3>
                            <p className="text-sm text-muted-foreground">Control de reinicio del panel de control</p>
                        </div>
                    </div>

                    <div className="flex-1 bg-secondary/30 rounded-2xl p-6 border border-border/50 space-y-4">
                        <div>
                            <p className="text-xs font-bold text-muted-foreground uppercase opacity-50 mb-2">Estado del Dashboard</p>
                            <div className="flex items-center gap-2">
                                <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                                <span className="text-sm font-bold tracking-tight">Servicio Operativo</span>
                            </div>
                        </div>

                        {restartStatus?.pending && (
                            <div className="p-3 bg-yellow-500/10 border border-yellow-500/20 rounded-xl">
                                <p className="text-xs font-bold text-yellow-500">Reinicio pendiente en {restartStatus.remaining?.toFixed(1)}s</p>
                            </div>
                        )}

                        <p className="text-xs text-muted-foreground leading-relaxed">
                            El reinicio del dashboard refrescará todos los servicios de la interfaz y cerrará las conexiones activas. Úsalo si notas inestabilidad en la conexión con el servidor.
                        </p>
                    </div>

                    <button
                        onClick={handleRestart}
                        className="w-full px-6 py-4 bg-secondary text-foreground rounded-2xl text-xs font-bold hover:bg-destructive/10 hover:text-destructive transition-all flex items-center justify-center gap-2 active:scale-95 border border-border"
                    >
                        <RotateCcw size={16} />
                        Reiniciar Interfaz Xaloc
                    </button>
                </div>
            </div>
        </div>
    );
}
