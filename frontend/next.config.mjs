/** @type {import('next').NextConfig} */
const backend = process.env.BACKEND_URL || "http://localhost:8000";

export default {
  output: "standalone",
  // The browser only ever talks to this origin; the backend (and the YouCam key) stay server-side.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};
