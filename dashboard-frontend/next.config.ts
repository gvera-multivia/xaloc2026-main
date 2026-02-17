import type { NextConfig } from "next";

const backendHost = (process.env.DASHBOARD_BACKEND_HOST || "127.0.0.1").trim() || "127.0.0.1";
const backendPort = (
  process.env.DASHBOARD_PORT_FIXED ||
  process.env.DASHBOARD_BACKEND_PORT ||
  "8787"
).trim() || "8787";
const backendBase = (
  process.env.DASHBOARD_BACKEND_URL ||
  `http://${backendHost}:${backendPort}`
).replace(/\/+$/, "");

const nextConfig: NextConfig = {
  turbopack: {
    root: process.cwd(),
  },
  images: {
    unoptimized: true,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendBase}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
