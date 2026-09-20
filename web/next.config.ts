import type { NextConfig } from "next";

// The FastAPI archive serves JSON at /api/*. In dev and in a single-host deploy,
// proxy through Next so the browser never needs CORS. Override with ARCHIVE_API.
const API = process.env.ARCHIVE_API ?? "http://127.0.0.1:8100";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API}/api/:path*` },
      { source: "/raw/:hash", destination: `${API}/raw/:hash` },
    ];
  },
};

export default nextConfig;
