'use client';

import React, { createContext, useContext, useEffect, useRef, useState, ReactNode } from 'react';
import { useAuth } from '@/lib/AuthContext';

type WebSocketContextType = {
  lastMessage: any;
  isConnected: boolean;
};

const WebSocketContext = createContext<WebSocketContextType | null>(null);

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<any>(null);
  const ws = useRef<WebSocket | null>(null);
  const reconnectTimeout = useRef<NodeJS.Timeout | null>(null);
  const { isAuthenticated, loading } = useAuth();

  useEffect(() => {
    const wsEnabled = (process.env.NEXT_PUBLIC_ENABLE_WS || '0').toLowerCase();
    const shouldEnableWs = wsEnabled === '1' || wsEnabled === 'true' || wsEnabled === 'yes' || wsEnabled === 'on';
    if (!shouldEnableWs) {
      setIsConnected(false);
      return;
    }

    if (loading || !isAuthenticated) {
      if (ws.current) {
        ws.current.close();
        ws.current = null;
      }
      setIsConnected(false);
      return;
    }

    const connect = () => {
      if (ws.current && (ws.current.readyState === WebSocket.OPEN || ws.current.readyState === WebSocket.CONNECTING)) {
        return;
      }
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      const baseWsUrl = process.env.NEXT_PUBLIC_WS_URL || `${protocol}//${host}/ws/dashboard`;
      const wsUrl = baseWsUrl;

      console.log('Connecting to WebSocket:', wsUrl);
      const socket = new WebSocket(wsUrl);

      socket.onopen = () => {
        console.log('WebSocket Connected');
        setIsConnected(true);
        if (reconnectTimeout.current) {
            clearTimeout(reconnectTimeout.current);
            reconnectTimeout.current = null;
        }
      };

      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setLastMessage(data);
        } catch (e) {
          console.error('WebSocket message parse error:', e);
        }
      };

      socket.onclose = (event) => {
        console.log('WebSocket Disconnected');
        setIsConnected(false);
        ws.current = null;
        // Do not retry when backend explicitly indicates service unavailable/auth required.
        if (event.code === 1013 || event.code === 4401) {
          if (event.code === 4401 && typeof window !== 'undefined') {
            try {
              window.localStorage.removeItem('dashboard_access_token');
            } catch {
              // ignore storage issues and force login route anyway
            }
            if (window.location.pathname !== '/login') {
              window.location.assign('/login');
            }
          }
          return;
        }
        // Reconnect logic
        reconnectTimeout.current = setTimeout(connect, 3000);
      };

      socket.onerror = (error) => {
          console.error('WebSocket Error:', error);
          socket.close();
      };

      ws.current = socket;
    };

    connect();

    return () => {
      if (ws.current) {
        ws.current.close();
      }
      if (reconnectTimeout.current) {
          clearTimeout(reconnectTimeout.current);
      }
    };
  }, [isAuthenticated, loading]);

  return (
    <WebSocketContext.Provider value={{ lastMessage, isConnected }}>
      {children}
    </WebSocketContext.Provider>
  );
}

export function useWebSocket() {
  const context = useContext(WebSocketContext);
  if (!context) {
    throw new Error('useWebSocket must be used within a WebSocketProvider');
  }
  return context;
}
