/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "**",
      },
    ],
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  },
  experimental: {
    // Allow useSearchParams in client components without Suspense during SSG
    missingSuspenseWithCSRBailout: false,
  },
};

module.exports = nextConfig;
