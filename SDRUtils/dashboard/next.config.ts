import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Turbopack is now stable in Next.js 15.3+
  // No need for experimental.turbo anymore
  // Turbopack is enabled by default with --turbo flag
  
  // Performance optimizations
  reactStrictMode: true,
  
  // Enable static optimization
  output: 'standalone',
  
  // Optimize images
  images: {
    unoptimized: true
  }
};

export default nextConfig;
