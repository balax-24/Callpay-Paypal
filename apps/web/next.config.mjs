const apiInternalUrl = (process.env.API_INTERNAL_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiInternalUrl}/:path*` }];
  },
};

export default nextConfig;
