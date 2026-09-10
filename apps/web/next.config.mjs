/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  devIndicators: false,
  // The API-backed Phase 3 browser probe can run beside production E2E.
  // Its managed server supplies an isolated directory so it cannot rewrite
  // the production routes manifest while that lane is validating it.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  async rewrites() {
    const apiOrigin = (process.env.RICK_API_INTERNAL_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
    return [
      { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
      { source: "/health/:path*", destination: `${apiOrigin}/health/:path*` },
    ];
  },
};

export default nextConfig;
