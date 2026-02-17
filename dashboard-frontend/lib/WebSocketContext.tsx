'use client';

import React, { createContext, useContext, useEffect, useRef, useState, ReactNode } from 'react';

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

  useEffect(() => {
    const connect = () => {
      // Logic to determine WS URL
      // Can be configured via env var NEXT_PUBLIC_WS_URL or hardcoded fallback
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.hostname;
      // Default to localhost:8000 if not specified
      const wsUrl = process.env.NEXT_PUBLIC_WS_URL || `${protocol}//${host}:8000/ws/dashboard`;

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

      socket.onclose = () => {
        console.log('WebSocket Disconnected');
        setIsConnected(false);
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
  }, []);

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
