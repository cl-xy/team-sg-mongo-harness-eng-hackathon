import path from "node:path";
import type { NextConfig } from "next";
const nextConfig: NextConfig = {
  outputFileTracingRoot: path.resolve(process.cwd(), ".."),
  turbopack: { root: path.resolve(process.cwd(), "..") },
  devIndicators: false,
};
export default nextConfig;
