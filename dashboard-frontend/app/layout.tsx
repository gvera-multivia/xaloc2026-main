import type { Metadata } from "next";
import "./globals.css";
import { WebSocketProvider } from "@/lib/WebSocketContext";
import { AuthProvider } from "@/lib/AuthContext";
import AppShell from "@/components/AppShell";

export const metadata: Metadata = {
  title: "Morrigan",
  description: "Morrigan es un dashboard de monitorización en tiempo real",
  icons: {
    icon: [
      { url: "/raven.webp", sizes: "256x256", type: "image/webp" },
      { url: "/favicon.ico", sizes: "32x32" },
    ],
    shortcut: "/favicon.ico",
    apple: "/raven.webp",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className="dark">
      <body
        className="antialiased min-h-screen bg-background text-foreground selection:bg-primary/30"
      >
        <AuthProvider>
          <WebSocketProvider>
            <AppShell>{children}</AppShell>
          </WebSocketProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
