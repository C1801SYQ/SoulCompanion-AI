import { defineConfig } from '@tarojs/cli';
import { safeCloudOrigin } from '../src/cloud/url';

// Only public client configuration belongs here. No credentials enter the bundle.
// Phase03 Pages deployments have no emotion backend; keep public builds explicitly synthetic.
const publicDemoOnly = process.env.PUBLIC_DEMO_ONLY === 'true' || process.env.CF_PAGES === '1';
const publicApiBaseUrl = process.env.PUBLIC_API_BASE_URL || '';
export default defineConfig<'vite'>({
  projectName: 'soulcompanion-client',
  date: '2026-10-03',
  designWidth: 750,
  deviceRatio: { 375: 2, 640: 1.17, 750: 1, 828: 0.905 },
  sourceRoot: 'src',
  outputRoot: process.env.TARO_ENV === 'weapp' ? 'dist-weapp' : 'dist',
  framework: 'react',
  compiler: 'vite',
  plugins: [],
  cache: { enable: false },
  defineConstants: {
    PUBLIC_API_URL: JSON.stringify(process.env.PUBLIC_API_URL || ''),
    PUBLIC_DEMO_ONLY: JSON.stringify(publicDemoOnly),
    PUBLIC_CLOUDBASE_ENV_ID: JSON.stringify(process.env.PUBLIC_CLOUDBASE_ENV_ID || 'soulcompanion-dev-d0dzo6f2a24211'),
    PUBLIC_CLOUDBASE_REGION: JSON.stringify(process.env.PUBLIC_CLOUDBASE_REGION || 'ap-shanghai'),
    PUBLIC_WECHAT_APP_ID: JSON.stringify(process.env.PUBLIC_WECHAT_APP_ID || 'wx11a055ed4dc69764'),
    PUBLIC_API_BASE_URL: JSON.stringify(publicApiBaseUrl),
    // Remove the SDK import at build time for public DEMO and unconfigured local builds.
    PUBLIC_CLOUD_ENABLED: JSON.stringify(!publicDemoOnly && safeCloudOrigin(publicApiBaseUrl)),
  },
  mini: {
    // Taro 4.3's Mini Program native-style importer uses Sass's legacy callback API.
    sassLoaderOption: { api: 'legacy' },
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
        '/pages/community/index': '/community',
        '/pages/knowledge/index': '/knowledge',
        '/pages/growth/index': '/growth',
        '/pages/profile/index': '/profile',
        '/pages/community/detail': '/community/detail',
        '/pages/community/compose': '/community/compose',
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
