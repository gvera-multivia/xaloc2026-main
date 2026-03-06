import { existsSync, readFileSync } from "fs";
import { resolve } from "path";
import type { NextConfig } from "next";

function readRootEnvValue(key: string): string | undefined {
  const envPath = resolve(process.cwd(), "..", ".env");
  if (!existsSync(envPath)) {
    return undefined;
  }

  const content = readFileSync(envPath, "utf8");
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }

    const separatorIndex = line.indexOf("=");
    if (separatorIndex <= 0) {
      continue;
    }

    const currentKey = line.slice(0, separatorIndex).trim();
    if (currentKey !== key) {
      continue;
    }

    const value = line.slice(separatorIndex + 1).trim();
    return value.replace(/^['"]|['"]$/g, "");
  }

  return undefined;
}

function resolveEnvValue(...keys: string[]): string | undefined {
  for (const key of keys) {
    const processValue = process.env[key]?.trim();
    if (processValue) {
      return processValue;
    }

    const rootEnvValue = readRootEnvValue(key)?.trim();
    if (rootEnvValue) {
      return rootEnvValue;
    }
  }

  return undefined;
}

const backendHost = resolveEnvValue("DASHBOARD_BACKEND_HOST") || "127.0.0.1";
const backendPort =
  resolveEnvValue("DASHBOARD_PORT_FIXED", "DASHBOARD_BACKEND_PORT") || "8788";
const backendBase = (
  resolveEnvValue("DASHBOARD_BACKEND_URL") || `http://${backendHost}:${backendPort}`
).replace(/\/+$/, "");

const nextConfig: NextConfig = {
  devIndicators: false,
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
