/** @type {import('next').NextConfig} */
const BACKEND = process.env.BACKEND_INTERNAL_URL || "http://localhost:8088";

const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/backend/:path*", destination: `${BACKEND}/api/v1/:path*` },
    ];
  },
};

export default nextConfig;
