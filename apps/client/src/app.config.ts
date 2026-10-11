export default defineAppConfig({
  pages: [
    'pages/community/index',
    'pages/knowledge/index',
    'pages/growth/index',
    'pages/profile/index',
    'pages/community/detail',
    'pages/community/compose',
    'pages/community/mine',
  ],
  // Ordinary packages share the existing app identity and preserve all tool URLs.
  subPackages: [
    { root: 'pages/home', pages: ['index'] },
    { root: 'pages/session', pages: ['index'] },
    { root: 'pages/insights', pages: ['index'] },
    { root: 'pages/reports', pages: ['index'] },
    { root: 'pages/settings', pages: ['index'] },
    { root: 'pages/ops', pages: ['index'] },
  ],
  lazyCodeLoading: 'requiredComponents',
  window: {
    navigationBarTitleText: '予怀',
    navigationBarBackgroundColor: '#f8f5ee',
    navigationBarTextStyle: 'black',
    backgroundColor: '#f8f5ee',
  },
});
