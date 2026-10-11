/** PC04 official CloudBase SDK UI; secrets and action ledgers use private acknowledged pipes. */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const readline = require('node:readline');
const { spawnSync } = require('node:child_process');
const ROOT = path.resolve(__dirname, '..');
const CLIENT = path.join(ROOT, 'apps/client');
const BUILD_ROOT = path.join(ROOT, '.test-artifacts/pc04-official-h5');
const ORIGIN = 'http://127.0.0.1:18404';
const ENV_ID = 'soulcompanion-dev-d0dzo6f2a24211';
const CLOUD_ORIGIN = `https://${ENV_ID}.api.tcloudbasegateway.com`;
const API_ORIGIN = `https://${ENV_ID}-1501181209.ap-shanghai.app.tcloudbase.com`;
const API_BASE = API_ORIGIN + '/api/v2';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ACTION_KEY = /^[A-Za-z0-9._:-]{1,64}$/;
const NAMESPACE = 'e5f8cf36c8b14f3d8546e8f96bed9239';
const CHECK_NAMES = ['official_sdk_two_account_login', 'guest_private_and_device_boundary', 'parent_public_nickname_ui',
  'post_pending_not_public', 'operator_post_approval_ui', 'public_post_and_filter_ui', 'comment_pending_then_approved_ui',
  'confirmed_like_bookmark_ui', 'report_and_independent_resolution_ui', 'own_withdrawal_and_public_unavailable_ui',
  'logout_clears_private_ui', 'auth_storage_absent', 'no_external_family_or_media_requests'];

function deterministicId(kind, owner, key) {
  if (!UUID.test(owner) || typeof key !== 'string') throw new Error('PRIVATE_ID_INVALID');
  const bytes = crypto.createHash('sha1').update(Buffer.from(NAMESPACE, 'hex')).update(JSON.stringify([kind, owner, key])).digest().subarray(0, 16);
  bytes[6] = (bytes[6] & 15) | 80; bytes[8] = (bytes[8] & 63) | 128;
  const hex = bytes.toString('hex'); return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function sourceHash() {
  const hash = crypto.createHash('sha256');
  function file(filename) { hash.update(path.relative(CLIENT, filename).split(path.sep).join('/')); hash.update(fs.readFileSync(filename)); }
  function walk(folder) { for (const entry of fs.readdirSync(folder, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const filename = path.join(folder, entry.name);
    if (entry.isDirectory()) walk(filename); else if (entry.isFile()) file(filename); else throw new Error('SOURCE_SYMLINK_DENIED');
  } }
  for (const folder of ['src', 'config']) walk(path.join(CLIENT, folder));
  for (const filename of ['package.json', 'tsconfig.json', 'babel.config.cjs', 'project.config.json']) file(path.join(CLIENT, filename));
  return hash.digest('hex');
}

function prepareBuild() {
  const before = sourceHash();
  const auth = fs.readFileSync(path.join(CLIENT, 'src/cloud/auth/platform.h5.ts'), 'utf8');
  if (!auth.includes("import('@cloudbase/js-sdk')") || auth.includes('FakeAuthAdapter')) throw new Error('OFFICIAL_SDK_SOURCE_REQUIRED');
  fs.mkdirSync(BUILD_ROOT, { recursive: true });
  const copy = fs.mkdtempSync(path.join(BUILD_ROOT, 'run-'));
  for (const folder of ['src', 'config']) fs.cpSync(path.join(CLIENT, folder), path.join(copy, folder), { recursive: true });
  for (const filename of ['package.json', 'tsconfig.json', 'babel.config.cjs', 'project.config.json']) fs.copyFileSync(path.join(CLIENT, filename), path.join(copy, filename));
  fs.symlinkSync(path.join(CLIENT, 'node_modules'), path.join(copy, 'node_modules'), process.platform === 'win32' ? 'junction' : 'dir');
  const env = { ...process.env, PUBLIC_DEMO_ONLY: 'false', CF_PAGES: '', PUBLIC_API_URL: '', PUBLIC_API_BASE_URL: API_ORIGIN,
    PUBLIC_CLOUDBASE_ENV_ID: ENV_ID, PUBLIC_CLOUDBASE_REGION: 'ap-shanghai', NODE_ENV: 'production' };
  for (const key of Object.keys(env)) if (/SECRET|TOKEN|APIKEY|API_KEY|PASSWORD|TENCENTCLOUD|TENCENT_SECRET/i.test(key)) delete env[key];
  const cli = require.resolve('@tarojs/cli/bin/taro', { paths: [CLIENT] });
  const log = fs.openSync(path.join(copy, 'build.log'), 'w');
  let result;
  try { result = spawnSync(process.execPath, [cli, 'build', '--type', 'h5'], { cwd: copy, env, stdio: ['ignore', log, log], timeout: 180000, windowsHide: true }); }
  finally { fs.closeSync(log); }
  if (result.status !== 0 || !fs.existsSync(path.join(copy, 'dist/index.html')) || sourceHash() !== before) throw new Error('OFFICIAL_H5_BUILD_FAILED_OR_SOURCE_CHANGED');
  fs.writeFileSync(path.join(BUILD_ROOT, 'current.json'), JSON.stringify({ directory: path.join(copy, 'dist'), source_hash: before, official_sdk: true,
    origin: ORIGIN, api_origin: API_ORIGIN, env_id: ENV_ID, demo: false }) + '\n');
  return { status: 'prepared', real_calls: false, official_sdk: true, source_hash: before };
}

function currentBuild() {
  const manifest = JSON.parse(fs.readFileSync(path.join(BUILD_ROOT, 'current.json'), 'utf8'));
  if (manifest.source_hash !== sourceHash() || manifest.official_sdk !== true || manifest.demo !== false || manifest.origin !== ORIGIN
    || manifest.api_origin !== API_ORIGIN || manifest.env_id !== ENV_ID) throw new Error('OFFICIAL_H5_BUILD_STALE');
  const directory = fs.realpathSync(manifest.directory), root = fs.realpathSync(BUILD_ROOT);
  if (!directory.startsWith(root + path.sep) || !fs.existsSync(path.join(directory, 'index.html'))) throw new Error('OFFICIAL_H5_BUILD_BOUNDARY');
  return directory;
}

async function serve(directory) {
  const root = fs.realpathSync(directory), staticPaths = new Set(['/']);
  function walk(folder) { for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
    const file = path.join(folder, entry.name);
    if (entry.isDirectory()) walk(file); else if (entry.isFile()) staticPaths.add('/' + path.relative(root, file).split(path.sep).join('/'));
  } }
  walk(root);
  const server = http.createServer((request, response) => {
    try {
      const url = new URL(request.url, ORIGIN);
      if (!['GET', 'HEAD'].includes(request.method) || url.search || !staticPaths.has(url.pathname)) throw new Error('STATIC_BOUNDARY');
      const target = fs.realpathSync(path.resolve(root, '.' + (url.pathname === '/' ? '/index.html' : decodeURIComponent(url.pathname))));
      if (!target.startsWith(root + path.sep) || !fs.statSync(target).isFile()) throw new Error('STATIC_BOUNDARY');
      const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
        '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff': 'font/woff', '.woff2': 'font/woff2' };
      response.writeHead(200, { 'Content-Type': types[path.extname(target)] || 'application/octet-stream', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
      if (request.method === 'HEAD') { response.end(); return; }
      const stream = fs.createReadStream(target); stream.once('error', () => response.destroy()); stream.pipe(response);
    } catch { response.writeHead(404).end(); }
  });
  server.on('clientError', (_, socket) => socket.destroy()); server.on('upgrade', (_, socket) => socket.destroy());
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(18404, '127.0.0.1', resolve); });
  return { staticPaths, close: () => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }) };
}

class SyntheticBoundary {
  constructor(users) { if (!Array.isArray(users) || users.length !== 2 || users.some(user => !UUID.test(user)) || users[0] === users[1]) throw new Error('PRIVATE_INPUT_INVALID'); this.users = users; this.post = null; this.comment = null; this.report = null; }
  read(pathname) {
    if (['/api/v2/me', '/api/v2/healthz', '/api/v2/readyz', '/api/v2/parent-profile', '/api/v2/community/posts',
      '/api/v2/me/community/posts', '/api/v2/me/community/comments', '/api/v2/me/community/bookmarks', '/api/v2/ops/moderation', '/api/v2/ops/content-reports'].includes(pathname)) return true;
    const id = '[0-9a-f-]{36}';
    return new RegExp(`^/api/v2/(?:community/posts/${id}(?:/comments)?|community/comments/${id}|me/community/(?:posts|comments)/${id}(?:/feedback|/relations)?|ops/moderation/(?:posts|comments)/${id})$`).test(pathname);
  }
  attempt(account, method, pathname, body, key) {
    if (![0, 1].includes(account)) throw new Error('SYNTHETIC_WRITE_DENIED');
    const expect = condition => { if (!condition) throw new Error('SYNTHETIC_WRITE_DENIED'); };
    const exact = fields => body && typeof body === 'object' && Object.keys(body).sort().join(',') === [...fields].sort().join(',');
    if (method === 'PUT' && pathname === '/api/v2/parent-profile') {
      expect(exact(['nickname']) && body.nickname === (account === 0 ? 'PC04合成家长甲' : 'PC04合成家长乙')); return { kind: 'nickname', account };
    }
    if (method === 'POST' && pathname === '/api/v2/community/posts') {
      expect(account === 0 && ACTION_KEY.test(key) && exact(['title', 'body', 'age_band', 'topic']) && body.title === 'PC04 合成验收：晚饭后的聊天'
        && body.body === 'PC04 合成验收内容：完全虚构，不含真实儿童、学校或家庭信息。' && body.age_band === '6-8' && body.topic === 'parent-child');
      const id = deterministicId('post', this.users[0], key); expect(this.post === null || this.post === id); this.post = id; return { kind: 'post', account, key, body: { ...body } };
    }
    if (method === 'POST' && pathname === `/api/v2/community/posts/${this.post}/comments`) {
      expect(account === 1 && this.post && ACTION_KEY.test(key) && exact(['body']) && body.body === 'PC04 合成验收评论：仅用于软件验证，无真实儿童信息。');
      const id = deterministicId('comment', this.users[1], key); expect(this.comment === null || this.comment === id); this.comment = id; return { kind: 'comment', account, key, body: { ...body }, post_id: this.post };
    }
    for (const relation of ['like', 'bookmark']) if (['PUT', 'DELETE'].includes(method) && pathname === `/api/v2/community/posts/${this.post}/${relation}`) {
      expect(account === 1 && this.post && (body === null || Object.keys(body).length === 0)); return { kind: 'relation', account, relation, target_id: this.post };
    }
    if (method === 'POST' && pathname === '/api/v2/community/content-reports') {
      expect(account === 1 && this.post && ACTION_KEY.test(key) && exact(['target_type', 'target_id', 'reason', 'detail']) && body.target_type === 'post'
        && body.target_id === this.post && body.reason === 'privacy' && body.detail === 'PC04 合成验收举报，不代表真实内容风险。');
      this.report = deterministicId('content_report', this.users[1], `post:${this.post}:1`); return { kind: 'report', account, key, target_id: this.post, body: { ...body } };
    }
    if (method === 'POST' && [`/api/v2/ops/moderation/posts/${this.post}/approve`, `/api/v2/ops/moderation/comments/${this.comment}/approve`].includes(pathname)) {
      expect(account === 1 && (pathname.includes('/posts/') ? this.post !== null : this.comment !== null) && ACTION_KEY.test(key)
        && exact(['expected_revision', 'reason']) && body.expected_revision === 1 && body.reason === 'PC04 合成验收：已检查全文与隐私边界。'); return null;
    }
    if (method === 'POST' && pathname === `/api/v2/ops/content-reports/${this.report}/resolve`) {
      expect(account === 1 && this.report && ACTION_KEY.test(key) && exact(['expected_revision', 'reason', 'decision']) && body.expected_revision === 1
        && body.decision === 'resolved' && body.reason === 'PC04 合成验收：只处理举报，不隐藏内容。'); return null;
    }
    if (method === 'DELETE' && [`/api/v2/community/posts/${this.post}`, `/api/v2/community/comments/${this.comment}`].includes(pathname)) {
      expect((pathname.includes('/posts/') ? account === 0 && this.post : account === 1 && this.comment) && (body === null || Object.keys(body).length === 0)); return null;
    }
    throw new Error('SYNTHETIC_WRITE_DENIED');
  }
}

function privateProtocol() {
  const reader = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  let firstResolve, sequence = 0;
  const initial = new Promise(resolve => { firstResolve = resolve; }), pending = new Map();
  reader.on('line', line => {
    try {
      if (line.length > 65536) throw new Error('PRIVATE_PIPE_INVALID');
      const value = JSON.parse(line);
      if (firstResolve) { const resolve = firstResolve; firstResolve = null; resolve(value); return; }
      if (Object.keys(value).join(',') !== 'ack' || !pending.has(value.ack)) throw new Error('PRIVATE_PIPE_INVALID');
      pending.get(value.ack)(); pending.delete(value.ack);
    } catch { for (const release of pending.values()) release(false); pending.clear(); }
  });
  return { initial, close: () => reader.close(), event: async value => {
    const id = ++sequence;
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => { pending.delete(id); reject(new Error('PRIVATE_PIPE_ACK_TIMEOUT')); }, 10000);
      pending.set(id, approved => { clearTimeout(timeout); approved === false ? reject(new Error('PRIVATE_PIPE_REJECTED')) : resolve(); });
      process.stdout.write(JSON.stringify({ type: 'event', sequence: id, event: value }) + '\n');
    });
  } };
}

async function acceptance(protocol) {
  const { chromium, expect } = require('@playwright/test');
  const input = await protocol.initial;
  if (!input || !/^pc04-[a-f0-9]{20}$/.test(input.nonce) || !Array.isArray(input.accounts) || input.accounts.length !== 2
    || input.accounts.some(account => !/^scphase04_[a-f0-9]{20}$/.test(account.username) || typeof account.password !== 'string' || account.password.length < 8 || account.password.length > 32)) throw new Error('PRIVATE_INPUT_INVALID');
  const boundary = new SyntheticBoundary(input.users), checks = {}, contexts = [], tokens = new Set(), cookieSnapshots = [], reads = new Set();
  let server, browser, violation = false, guestPrivate = 0;
  const check = (name, value = true) => { if (!value || !CHECK_NAMES.includes(name)) throw new Error('BROWSER_ASSERTION_FAILED'); checks[name] = true; };
  const frame = page => page.locator('.taro_page_show.taro_page_stationed:not(.taro_page_shade):visible').last();
  const element = (page, id) => frame(page).locator(`[data-testid="${id}"]:visible,[id="${id}"]:visible`).first();
  const fill = (page, id, value) => element(page, id).locator('input,textarea').first().fill(value);
  async function ready(page, route) { await page.waitForFunction(slug => {
    const frames = [...document.querySelectorAll('.taro_page_show.taro_page_stationed:not(.taro_page_shade)')].filter(node => {
      const rect = node.getBoundingClientRect(); return rect.width > 0 && Math.abs(rect.left) < 1 && getComputedStyle(node).display !== 'none';
    });
    return frames.length === 1 && ['/' + slug, '/pages/' + slug, '/pages/' + slug + '/index'].includes(frames[0].id.split('?')[0]) && getComputedStyle(frames[0]).transform === 'none';
  }, route); }
  async function primary(page, name) { await element(page, 'nav-' + name).click(); await ready(page, name); }
  async function signIn(page, account) {
    await fill(page, 'pc-community-username', input.accounts[account].username); await fill(page, 'pc-community-password', input.accounts[account].password);
    await element(page, 'pc-community-sign-in').click(); await expect(element(page, 'pc-community-auth')).toHaveText('已登录');
  }
  async function actor(account, route) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce', serviceWorkers: 'block', acceptDownloads: false });
    contexts.push(context);
    await context.addInitScript(() => {
      window.__pc04CloudProbe = { media: 0, permissions: 0, storage: [] };
      if (navigator.mediaDevices) {
        navigator.mediaDevices.getUserMedia = async () => { window.__pc04CloudProbe.media++; throw new Error('MEDIA_BOUNDARY'); };
        navigator.mediaDevices.enumerateDevices = async () => { window.__pc04CloudProbe.media++; throw new Error('MEDIA_BOUNDARY'); };
      }
      if (navigator.permissions) { const original = navigator.permissions.query.bind(navigator.permissions); navigator.permissions.query = value => {
        if (['camera', 'microphone'].includes(value.name)) { window.__pc04CloudProbe.permissions++; return Promise.reject(new Error('MEDIA_BOUNDARY')); } return original(value);
      }; }
      const original = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) { window.__pc04CloudProbe.storage.push([String(key), String(value)]); return original.call(this, key, value); };
    });
    await context.route('**/*', async routeHandle => {
      const request = routeHandle.request(), url = new URL(request.url()), method = request.method();
      try {
        if (url.username || url.password || url.hash) throw new Error('NETWORK_BOUNDARY');
        if (url.origin === ORIGIN) {
          if (!['GET', 'HEAD'].includes(method) || url.search || !server.staticPaths.has(url.pathname)) throw new Error('NETWORK_BOUNDARY');
        } else if (url.origin === CLOUD_ORIGIN) {
          if (account === null || !url.pathname.startsWith('/auth/v1/') || !['GET', 'POST', 'OPTIONS'].includes(method)) throw new Error('NETWORK_BOUNDARY');
        } else if (url.origin === API_ORIGIN) {
          const authorization = request.headers().authorization || '';
          if (account === null && (authorization || !url.pathname.startsWith('/api/v2/community/'))) { guestPrivate++; throw new Error('NETWORK_BOUNDARY'); }
          if (authorization.startsWith('Bearer ') && !tokens.has(authorization.slice(7))) {
            tokens.add(authorization.slice(7)); await protocol.event({ kind: 'token', account, token: authorization.slice(7) });
          }
          if (method === 'GET') { if (!boundary.read(url.pathname)) throw new Error('NETWORK_BOUNDARY'); }
          else if (method === 'OPTIONS') {
            if (!url.pathname.startsWith('/api/v2/community/') && !boundary.read(url.pathname) && !url.pathname.startsWith('/api/v2/ops/')) throw new Error('NETWORK_BOUNDARY');
          } else {
            const type = request.headers()['content-type'] || '';
            if (type && !type.startsWith('application/json')) throw new Error('NETWORK_BOUNDARY');
            const body = request.postData() ? JSON.parse(request.postData()) : null;
            const event = boundary.attempt(account, method, url.pathname, body, request.headers()['idempotency-key']);
            if (event) await protocol.event(event);
          }
        } else throw new Error('NETWORK_BOUNDARY');
        await routeHandle.continue();
      } catch { violation = true; await routeHandle.abort().catch(() => undefined); }
    });
    const page = await context.newPage(); page.setDefaultTimeout(60000); page.on('pageerror', () => { violation = true; });
    page.on('response', response => {
      const url = new URL(response.url());
      if (account !== null && url.origin === API_ORIGIN && url.pathname === '/api/v2/parent-profile'
        && response.request().method() === 'PUT' && response.status() === 200) {
        const read = response.json().then(async value => {
          if (value.nickname !== (account === 0 ? 'PC04合成家长甲' : 'PC04合成家长乙')) throw new Error('NICKNAME_RECEIPT_INVALID');
          await protocol.event({ kind: 'nickname_settled', account });
        }).catch(() => { violation = true; });
        reads.add(read); void read.finally(() => reads.delete(read));
        return;
      }
      if (account === null || url.origin !== CLOUD_ORIGIN || !url.pathname.startsWith('/auth/v1/') || response.status() !== 200) return;
      const inspect = async value => {
        if (!value || typeof value !== 'object') return;
        for (const [key, item] of Object.entries(value)) if (/^(?:access_token|refresh_token|session_key|sessionKey)$/.test(key) && typeof item === 'string' && item) {
          tokens.add(item);
          // Only access tokens can be revoked by the introspected signout API.
          if (key === 'access_token') await protocol.event({ kind: 'token', account, token: item });
        } else if (item && typeof item === 'object') await inspect(item);
      };
      const read = response.json().then(inspect).catch(() => { violation = true; }); reads.add(read); void read.finally(() => reads.delete(read));
    });
    await page.goto(`${ORIGIN}/#/${route}`, { waitUntil: 'domcontentloaded' }); await ready(page, route);
    return page;
  }
  try {
    server = await serve(currentBuild()); browser = await chromium.launch({ headless: true });
    // No traces, HAR, console capture, screenshots, downloads or SDK substitutions.
    const guest = await actor(null, 'community'), a = await actor(0, 'profile'), b = await actor(1, 'profile');
    await expect(element(guest, 'community-real-badge')).toContainText('REAL');
    check('guest_private_and_device_boundary', guestPrivate === 0);
    await signIn(a, 0); await signIn(b, 1); check('official_sdk_two_account_login');
    for (const [page, account] of [[a, 0], [b, 1]]) {
      await expect(element(page, 'pc-community-nickname-saved')).toBeVisible(); await fill(page, 'pc-community-nickname', account === 0 ? 'PC04合成家长甲' : 'PC04合成家长乙');
      await element(page, 'pc-community-nickname-save').click(); await expect(element(page, 'pc-community-nickname-saved')).toContainText(account === 0 ? 'PC04合成家长甲' : 'PC04合成家长乙');
    }
    check('parent_public_nickname_ui');
    await primary(a, 'community'); await element(a, 'pc-compose-entry').click(); await ready(a, 'community/compose');
    await fill(a, 'pc-title-input', 'PC04 合成验收：晚饭后的聊天'); await fill(a, 'pc-body-input', 'PC04 合成验收内容：完全虚构，不含真实儿童、学校或家庭信息。');
    await element(a, 'pc-compose-age-6-8').click(); await element(a, 'pc-compose-topic-parent-child').click(); await element(a, 'pc-compose-preview').click();
    await expect(element(a, 'pc-draft-preview')).toBeVisible(); await element(a, 'pc-compose-submit').click();
    await expect(element(a, 'pc-compose-submitted')).toContainText('已提交审核');
    if (!boundary.post) throw new Error('SYNTHETIC_TARGET_MISSING');
    // Guest direct read proves pending cannot be recovered through an ID URL.
    const pending = await guest.request.get(`${API_BASE}/community/posts/${boundary.post}`); check('post_pending_not_public', pending.status() === 404);
    const ops = await actor(1, 'ops'); await signIn(ops, 1); await expect(element(ops, 'ops-tab-content')).toBeVisible();
    async function moderate(id, kind) {
      await element(ops, 'ops-tab-content').click(); await element(ops, 'ops-kind-' + kind).click(); await element(ops, 'ops-status-pending').click(); await element(ops, 'ops-refresh').click();
      await element(ops, 'ops-content-' + id).click(); await expect(element(ops, 'ops-full-body')).toBeVisible(); await fill(ops, 'ops-reason', 'PC04 合成验收：已检查全文与隐私边界。');
      await element(ops, 'ops-approve').click(); await expect(element(ops, 'ops-message')).toContainText('动作回执已确认');
    }
    await moderate(boundary.post, 'post'); check('operator_post_approval_ui');
    await element(guest, 'pc-feed-refresh').click(); await element(guest, 'pc-age-6-8').click(); await element(guest, 'pc-topic-parent-child').click();
    await expect(element(guest, 'pc-open-' + boundary.post)).toBeVisible(); await element(guest, 'pc-open-' + boundary.post).click(); await ready(guest, 'community/detail');
    await expect(element(guest, 'pc-real-post-body')).toContainText('完全虚构'); check('public_post_and_filter_ui');
    await primary(b, 'community'); await element(b, 'pc-open-' + boundary.post).click(); await ready(b, 'community/detail'); await element(b, 'pc-comment-open').click();
    await expect(element(b, 'pc-comment-submit')).toBeEnabled(); await fill(b, 'pc-comment-input', 'PC04 合成验收评论：仅用于软件验证，无真实儿童信息。');
    await element(b, 'pc-comment-submit').click(); await expect(element(b, 'pc-comment-message')).toContainText('评论已提交审核');
    if (!boundary.comment) throw new Error('SYNTHETIC_TARGET_MISSING');
    const pendingComment = await guest.request.get(`${API_BASE}/community/comments/${boundary.comment}`);
    if (pendingComment.status() !== 404) throw new Error('PENDING_COMMENT_VISIBLE');
    await moderate(boundary.comment, 'comment'); await element(b, 'pc-comments-refresh').click();
    await expect(frame(b).locator(`[data-comment-id="${boundary.comment}"]`)).toContainText('PC04合成家长乙'); check('comment_pending_then_approved_ui');
    await expect(element(b, 'pc-post-like')).toBeEnabled(); await element(b, 'pc-post-like').click(); await expect(element(b, 'pc-post-like')).toHaveAttribute('aria-pressed', 'true');
    await element(b, 'pc-post-bookmark').click(); await expect(element(b, 'pc-post-bookmark')).toHaveAttribute('aria-pressed', 'true'); check('confirmed_like_bookmark_ui');
    await element(b, 'pc-report-post-' + boundary.post).click(); await fill(b, 'pc-report-detail-post-' + boundary.post, 'PC04 合成验收举报，不代表真实内容风险。');
    await element(b, 'pc-report-submit-post-' + boundary.post).click(); await expect(frame(b)).toContainText('举报已提交。');
    await element(ops, 'ops-tab-reports').click(); await element(ops, 'ops-reports-refresh').click(); await element(ops, 'ops-report-' + boundary.report).click();
    await fill(ops, 'ops-reason', 'PC04 合成验收：只处理举报，不隐藏内容。'); await element(ops, 'ops-resolve').click(); await expect(element(ops, 'ops-message')).toContainText('处理回执已确认');
    const retained = await guest.request.get(`${API_BASE}/community/posts/${boundary.post}`); check('report_and_independent_resolution_ui', retained.status() === 200);
    await element(a, 'pc-compose-mine').click(); await ready(a, 'community/mine'); await element(a, 'pc-mine-withdraw-' + boundary.post).click(); await element(a, 'pc-mine-confirm-withdraw-' + boundary.post).click();
    await expect(frame(a).locator(`[data-owned-id="${boundary.post}"]`)).toHaveAttribute('data-content-status', 'deleted');
    const unavailable = await guest.request.get(`${API_BASE}/community/posts/${boundary.post}`); if (unavailable.status() !== 404) throw new Error('WITHDRAW_NOT_PUBLICLY_HIDDEN');
    await primary(b, 'profile'); await element(b, 'pc-my-comments').click(); await ready(b, 'community/mine'); await element(b, 'pc-mine-withdraw-' + boundary.comment).click(); await element(b, 'pc-mine-confirm-withdraw-' + boundary.comment).click();
    await expect(frame(b).locator(`[data-owned-id="${boundary.comment}"]`)).toHaveAttribute('data-content-status', 'deleted'); check('own_withdrawal_and_public_unavailable_ui');
    for (const page of [a, b, ops]) {
      cookieSnapshots.push(...await page.context().cookies());
      if (page !== ops) await primary(page, 'profile');
      await element(page, 'pc-community-sign-out').click(); await expect(element(page, 'pc-community-auth')).toHaveText('未登录');
      await expect(element(page, 'pc-community-nickname-saved')).toHaveCount(0);
    }
    check('logout_clears_private_ui'); await Promise.all(reads);
    const passwords = input.accounts.map(account => account.password), sensitive = [...tokens, ...passwords];
    for (const context of contexts) {
      cookieSnapshots.push(...await context.cookies());
      for (const page of context.pages()) {
        const safe = await page.evaluate(values => {
          const probe = window.__pc04CloudProbe;
          return probe.media === 0 && probe.permissions === 0 && [...Object.entries(localStorage), ...Object.entries(sessionStorage), ...probe.storage]
            .every(([key, value]) => !/(?:access.?token|refresh.?token|session.?key)/i.test(key) && values.every(secret => !value.includes(secret))
              && !/"(?:access_token|refresh_token|session_key|sessionKey)"\s*:/i.test(value));
        }, sensitive);
        if (!safe) throw new Error('STORAGE_OR_DEVICE_BOUNDARY');
      }
    }
    check('auth_storage_absent', cookieSnapshots.every(cookie => !/(?:access.?token|refresh.?token|session)/i.test(cookie.name)
      && sensitive.every(secret => !cookie.value.includes(secret) && !decodeURIComponent(cookie.value).includes(secret))));
    check('no_external_family_or_media_requests', !violation && guestPrivate === 0);
    if (Object.keys(checks).length !== CHECK_NAMES.length) throw new Error('BROWSER_ACCEPTANCE_INCOMPLETE');
    return { status: 'pass', checks };
  } finally {
    for (const account of input.accounts) account.password = '';
    for (const context of contexts) await context.close().catch(() => undefined);
    if (browser) await browser.close().catch(() => undefined);
    if (server) await server.close();
  }
}

async function main() {
  if (process.argv.includes('--verify-build')) {
    try { currentBuild(); process.stdout.write(JSON.stringify({ status: 'ready', real_calls: false, official_sdk: true }) + '\n'); }
    catch { process.stdout.write(JSON.stringify({ status: 'blocked', real_calls: false, code: 'OFFICIAL_H5_BUILD_REQUIRED' }) + '\n'); process.exitCode = 1; }
    return;
  }
  if (process.argv.includes('--prepare-only')) {
    try { process.stdout.write(JSON.stringify(prepareBuild()) + '\n'); }
    catch { process.stdout.write(JSON.stringify({ status: 'failed', real_calls: false, code: 'OFFICIAL_H5_BUILD_FAILED' }) + '\n'); process.exitCode = 1; }
    return;
  }
  if (!process.argv.includes('--apply')) { process.stdout.write(JSON.stringify({ status: 'plan', real_calls: false, requires: ['--apply', '--cloud-write-authorized'], official_sdk: true }) + '\n'); return; }
  if (!process.argv.includes('--cloud-write-authorized')) { process.stdout.write(JSON.stringify({ status: 'blocked', real_calls: false, code: 'PC04_CLOUD_WRITE_AUTHORIZATION_REQUIRED' }) + '\n'); process.exitCode = 1; return; }
  if (!process.argv.includes('--private-protocol') || process.env.PC04_PRIVATE_PROTOCOL !== '1' || process.stdout.isTTY || process.stdin.isTTY) {
    process.stdout.write(JSON.stringify({ status: 'blocked', real_calls: false, code: 'PRIVATE_PARENT_PIPE_REQUIRED' }) + '\n'); process.exitCode = 1; return;
  }
  const protocol = privateProtocol();
  try { const result = await acceptance(protocol); process.stdout.write(JSON.stringify({ type: 'result', result }) + '\n'); }
  catch { process.stdout.write(JSON.stringify({ type: 'result', result: { status: 'failed', code: 'PC04_BROWSER_ACCEPTANCE_FAILED' } }) + '\n'); process.exitCode = 1; }
  finally { protocol.close(); }
}

module.exports = { deterministicId, SyntheticBoundary, CHECK_NAMES, prepareBuild, currentBuild };
if (require.main === module) void main();
