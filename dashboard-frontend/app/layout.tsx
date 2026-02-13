import type { Metadata } from "next";
import "./globals.css";
import Navbar from "@/components/Navbar";

export const metadata: Metadata = {
  title: "Xaloc Operations Console",
  description: "Monitoreo y control de procesos en tiempo real",
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
        <Navbar />
        <main className="pt-24 pb-12 container mx-auto px-4">
          {children}
        </main>
      </body>
    </html>
  );
}
