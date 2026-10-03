import { defineConfig } from '@tarojs/cli';

// Only public client configuration belongs here. No credentials enter the bundle.
// Phase03 Pages deployments have no emotion backend; keep public builds explicitly synthetic.
const publicDemoOnly = process.env.PUBLIC_DEMO_ONLY === 'true' || process.env.CF_PAGES === '1';
export default defineConfig<'vite'>({
  projectName: 'soulcompanion-client',
  date: '2026-10-03',
  designWidth: 750,
  deviceRatio: { 375: 2, 640: 1.17, 750: 1, 828: 0.905 },
  sourceRoot: 'src',
  outputRoot: 'dist',
  framework: 'react',
  compiler: 'vite',
  plugins: [],
  cache: { enable: false },
  defineConstants: {
    PUBLIC_API_URL: JSON.stringify(process.env.PUBLIC_API_URL || ''),
    PUBLIC_DEMO_ONLY: JSON.stringify(publicDemoOnly),
  },
  mini: {
    minifyXML: { collapseWhitespace: false },
    postcss: {
      pxtransform: { enable: true },
      cssModules: { enable: false },
    },
  },
  h5: {
    publicPath: '/',
    staticDirectory: 'static',
    esnextModules: ['@taroify'],
    router: {
      mode: 'hash',
      customRoutes: {
        '/pages/home/index': '/home',
        '/pages/session/index': '/session',
        '/pages/insights/index': '/insights',
        '/pages/reports/index': '/reports',
        '/pages/settings/index': '/settings',
      },
    },
    devServer: {
      host: '127.0.0.1', port: 5173, open: false, strictPort: true,
      cors: false, allowedHosts: ['localhost', '127.0.0.1'],
    },
    postcss: { pxtransform: { enable: false }, cssModules: { enable: false } },
  },
});
