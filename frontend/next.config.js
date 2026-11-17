/** @type {import('next').NextConfig} */
// `npm run build` exports a static site to ./out which the FastAPI server serves (single origin,
// password-protected). `npm run dev` proxies /api to the local backend.
const EXPORT = process.env.NODE_ENV === "production" || process.env.NEXT_EXPORT === "1";
const BACKEND = process.env.BACKEND_URL || "http://127.0.0.1:8000";
module.exports = {
  reactStrictMode: true,
  trailingSlash: EXPORT,
  images: { unoptimized: true },
  ...(EXPORT
    ? { output: "export" }
    : { async rewrites() { return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }]; } }),
};
