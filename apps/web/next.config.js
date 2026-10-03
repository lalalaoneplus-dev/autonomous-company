/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  outputFileTracingIncludes: {
    '/*': ['./node_modules/.pnpm/@swc+helpers@*/node_modules/@swc/helpers/**/*'],
  },
};
module.exports = nextConfig;
