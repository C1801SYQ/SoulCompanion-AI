/** PC04: production H5 UI + actual FastAPI routes with loopback-only synthetic adapters. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const http = require('node:http');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { randomUUID } = require('node:crypto');
const { chromium, expect } = require('@playwright/test');

const ROOT = path.resolve(__dirname, '..');
const CLIENT = path.join(ROOT, 'apps', 'client');
const COPY_ROOT = path.join(ROOT, '.test-artifacts', 'pc04-integration-test-client');
const OUTPUT = path.join(ROOT, '.test-artifacts', 'pc04-community-integration');
const PYTHON = process.env.SOULCOMPANION_PYTHON || 'python';
const SCREENS = [{ width: 375, height: 812 }, { width: 390, height: 844 }, { width: 430, height: 932 },
  { width: 600, height: 900 }, { width: 767, height: 1024 }, { width: 768, height: 1024 }, { width: 1440, height: 900 }];
const AGES = ['0-2', '3-5', '6-8', '9-12', '13-15', '16-18'];
const TOPICS = ['parent-child', 'emotional-support', 'daily-habits', 'school-transition', 'learning-peers', 'adolescence', 'parent-growth'];
const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const frame = page => page.locator('.taro_page_show.taro_page_stationed:not(.taro_page_shade):visible').last();
const element = (page, id) => frame(page).locator(`[data-testid="${id}"]:visible, [id="${id}"]:visible`).first();

function allowedApi(method, pathname) {
  if (!['GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS'].includes(method)) return false;
  // An OPTIONS preflight is accepted only for an otherwise named resource.
  if (pathname === '/api/v2/parent-profile') return ['GET', 'PUT', 'OPTIONS'].includes(method);
  const patterns = {
    GET: [`/api/v2/community/posts`, `/api/v2/community/posts/${UUID}(?:/comments)?`, `/api/v2/community/comments/${UUID}`,
      '/api/v2/me/community/(?:posts|comments|bookmarks)', `/api/v2/me/community/(?:posts|comments)/${UUID}(?:/feedback|/relations)?`,
      '/api/v2/ops/(?:moderation|content-reports)', `/api/v2/ops/moderation/(?:posts|comments)/${UUID}`],
    POST: ['/api/v2/community/posts', `/api/v2/community/posts/${UUID}/comments`, '/api/v2/community/content-reports',
      `/api/v2/ops/moderation/(?:posts|comments)/${UUID}/(?:approve|reject|hide)`, `/api/v2/ops/content-reports/${UUID}/resolve`],
    PATCH: [`/api/v2/community/posts/${UUID}`],
    PUT: [`/api/v2/community/posts/${UUID}/(?:like|bookmark)`],
    DELETE: [`/api/v2/community/(?:posts|comments)/${UUID}`, `/api/v2/community/posts/${UUID}/(?:like|bookmark)`],
  };
  const methods = method === 'OPTIONS' ? Object.keys(patterns) : [method];
  return methods.some(value => patterns[value].some(pattern => new RegExp(`^${pattern}$`).test(pathname)));
}

function allowedRequest(urlString, method, origin, apiOrigin, staticPaths) {
  let url;
  try { url = new URL(urlString); } catch { return false; }
  if (url.username || url.password || url.hash) return false;
  if (url.origin === apiOrigin) return allowedApi(method, url.pathname);
  if (url.origin !== origin || !['GET', 'HEAD'].includes(method) || url.search) return false;
  let pathname;
  try { pathname = decodeURIComponent(url.pathname); } catch { return false; }
  return !pathname.includes('\\') && !pathname.includes('\0') && !pathname.startsWith('/api/') && staticPaths.has(pathname);
}

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

/** Every test build is a fresh ignored directory. No production file or installation is mutated. */
function prepareTestClient(apiOrigin) {
  assert.equal(new URL(apiOrigin).hostname, '127.0.0.1');
  assert.equal(new URL(apiOrigin).protocol, 'http:');
  fs.mkdirSync(COPY_ROOT, { recursive: true });
  const copy = fs.mkdtempSync(path.join(COPY_ROOT, 'run-'));
  assert.ok(copy.startsWith(COPY_ROOT + path.sep));
  for (const folder of ['src', 'config']) fs.cpSync(path.join(CLIENT, folder), path.join(copy, folder), { recursive: true });
  for (const file of ['package.json', 'tsconfig.json', 'babel.config.cjs', 'project.config.json']) fs.copyFileSync(path.join(CLIENT, file), path.join(copy, file));
  fs.symlinkSync(path.join(CLIENT, 'node_modules'), path.join(copy, 'node_modules'), process.platform === 'win32' ? 'junction' : 'dir');
  const fake = `// TEST COPY ONLY: never selected by the production platform factory.\nimport { FakeAuthAdapter } from './fake';\nimport { CloudError, type SignInInput, type SourcePlatform } from '../types';\nimport type { CloudConfig } from '../config';\nclass BrowserFixtureAuth extends FakeAuthAdapter {\n  async signIn(input?: SignInInput) {\n    const account = input?.username;\n    if (!['a', 'b', 'c'].includes(account ?? '')) throw new CloudError('unauthorized');\n    this.setAccount('synthetic-browser-' + account, 'community-account-' + account);\n  }\n}\nexport function createCloudAuthAdapter(_config: CloudConfig) { return new BrowserFixtureAuth(); }\nexport const cloudSourcePlatform: SourcePlatform = 'web';\n`;
  fs.writeFileSync(path.join(copy, 'src', 'cloud', 'auth', 'platform.h5.ts'), fake);
  return copy;
}

async function buildClient(copy, apiOrigin, logFile) {
  const cli = require.resolve('@tarojs/cli/bin/taro', { paths: [CLIENT] });
  const env = { ...process.env, NODE_ENV: 'production', PUBLIC_DEMO_ONLY: 'false', CF_PAGES: '',
    PUBLIC_API_URL: '', PUBLIC_API_BASE_URL: apiOrigin, PUBLIC_CLOUDBASE_ENV_ID: 'synthetic-community-environment',
    PUBLIC_CLOUDBASE_REGION: 'ap-shanghai' };
  // These processes never need real credentials. Drop known cloud secret variables.
  for (const key of Object.keys(env)) if (/SECRET|TOKEN|APIKEY|API_KEY|PASSWORD|CLOUDBASE_ACCESS|TENCENTCLOUD|TENCENT_SECRET/i.test(key)) delete env[key];
  const output = fs.openSync(logFile, 'w');
  const child = spawn(process.execPath, [cli, 'build', '--type', 'h5'], { cwd: copy, env, stdio: ['ignore', output, output], windowsHide: true });
  try {
    const [code] = await once(child, 'exit');
    assert.equal(code, 0, 'Isolated H5 build failed; see build.log');
    assert.ok(fs.existsSync(path.join(copy, 'dist', 'index.html')));
  } finally { fs.closeSync(output); }
}

async function staticServer(directory, port) {
  const root = fs.realpathSync(directory), origin = `http://127.0.0.1:${port}`;
  const staticPaths = new Set(['/']);
  function walk(folder) { for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
    const filename = path.join(folder, entry.name);
    if (entry.isDirectory()) walk(filename);
    else if (entry.isFile()) staticPaths.add('/' + path.relative(root, filename).split(path.sep).join('/'));
  } }
  walk(root);
  const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff': 'font/woff', '.woff2': 'font/woff2' };
  const server = http.createServer((request, response) => {
    try {
      const url = new URL(request.url, origin);
      if (!allowedRequest(url.href, request.method, origin, 'http://127.0.0.1:1', staticPaths)) throw new Error('Static boundary');
      const file = fs.realpathSync(path.resolve(root, '.' + (url.pathname === '/' ? '/index.html' : decodeURIComponent(url.pathname))));
      if (!file.startsWith(root + path.sep) || !fs.statSync(file).isFile()) throw new Error('File boundary');
      response.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
      if (request.method === 'HEAD') { response.end(); return; }
      const stream = fs.createReadStream(file); stream.once('error', error => response.destroy(error)); stream.pipe(response);
    } catch { response.writeHead(request.method === 'GET' ? 404 : 405); response.end(); }
  });
  server.on('clientError', (_, socket) => socket.destroy());
  server.on('upgrade', (_, socket) => socket.destroy());
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
  return { origin, staticPaths, close: () => new Promise((resolve, reject) => {
    server.close(error => error ? reject(error) : resolve()); server.closeAllConnections();
  }) };
}

function installPrivacyProbe() {
  window.__pc04Probe = { media: 0, enumerate: 0, permissions: 0 };
  if (navigator.mediaDevices) {
    navigator.mediaDevices.getUserMedia = async () => { window.__pc04Probe.media++; throw new Error('Community requested media'); };
    navigator.mediaDevices.enumerateDevices = async () => { window.__pc04Probe.enumerate++; throw new Error('Community enumerated devices'); };
  }
  if (navigator.permissions) {
    const query = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = descriptor => ['camera', 'microphone'].includes(descriptor.name)
      ? (window.__pc04Probe.permissions++, Promise.reject(new Error('Community requested permission'))) : query(descriptor);
  }
}

async function readyApi(child, apiOrigin) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    assert.equal(child.exitCode, null, 'Local API fixture exited before readiness');
    try { if ((await fetch(apiOrigin + '/api/v2/healthz', { signal: AbortSignal.timeout(1000) })).status === 200) return; } catch { /* Condition polling, never a UI race delay. */ }
    await new Promise(resolve => setImmediate(resolve));
  }
  throw new Error('Local API readiness deadline exceeded');
}

async function go(page, origin, route) {
  await page.goto(`${origin}/#/${route}`);
  await waitRoute(page, route);
}

async function waitRoute(page, route) {
  await page.waitForFunction(expected => {
    const frames = [...document.querySelectorAll('.taro_page_show.taro_page_stationed:not(.taro_page_shade)')].filter(node => {
      const style = getComputedStyle(node), rect = node.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && Math.abs(rect.left) < 1;
    });
    const slug = expected.split('?')[0];
    return frames.length === 1 && ['/' + slug, '/pages/' + slug, '/pages/' + slug + '/index'].includes(frames[0].id.split('?')[0]) && getComputedStyle(frames[0]).transform === 'none';
  }, route);
}

async function fill(page, id, text) {
  // Taro first mounts a custom-element shell, then hydrates its native control.
  // Await the actual input instead of sampling count() during hydration.
  await element(page, id).locator('input,textarea').first().fill(text);
}

async function signIn(page, account) {
  await fill(page, 'pc-community-username', account);
  await fill(page, 'pc-community-password', 'synthetic-only');
  await element(page, 'pc-community-sign-in').click();
  await expect(element(page, 'pc-community-auth')).toHaveText('已登录');
}

async function saveNickname(page, nickname) {
  await expect(element(page, 'pc-community-nickname-saved')).toBeVisible();
  await fill(page, 'pc-community-nickname', nickname);
  await element(page, 'pc-community-nickname-save').click();
  await expect(element(page, 'pc-community-nickname-saved')).toContainText(nickname);
}

async function acceptance() {
  fs.mkdirSync(OUTPUT, { recursive: true });
  const run = fs.mkdtempSync(path.join(OUTPUT, 'run-'));
  const evidence = { status: 'running', started_at: new Date().toISOString(), fixture: 'Production UI and FastAPI with synthetic auth/in-memory storage; loopback only',
    checks: [], responsive: [], screenshots: [], cleanup: [], privacy: {}, limitations: [
      'CloudBase SDK login and real cloud resources are NOT TESTED by this local fake-adapter suite',
      'WeChat DevTools and physical devices are NOT TESTED by Chromium H5',
    ] };
  const save = () => {
    const json = JSON.stringify(evidence, null, 2) + '\n';
    fs.writeFileSync(path.join(run, 'results.json'), json); fs.writeFileSync(path.join(OUTPUT, 'results.json'), json);
    const escape = text => String(text).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[character]);
    const cases = evidence.checks.map(check => `<testcase classname="pc04.local-community" name="${escape(check.name)}"/>`);
    if (evidence.failure) cases.push(`<testcase classname="pc04.local-community" name="integration failure"><failure message="${escape(evidence.failure.type)}">${escape(evidence.failure.message)}</failure></testcase>`);
    const xml = `<?xml version="1.0" encoding="UTF-8"?><testsuite name="PC04 local community integration" tests="${cases.length}" failures="${evidence.failure ? 1 : 0}">${cases.join('')}</testsuite>\n`;
    fs.writeFileSync(path.join(run, 'results.xml'), xml); fs.writeFileSync(path.join(OUTPUT, 'results.xml'), xml);
    const report = `<!doctype html><meta charset="utf-8"><title>PC04 local integration</title><h1>PC04 local integration: ${escape(evidence.status)}</h1><p>${escape(evidence.fixture)}</p><ul>${evidence.checks.map(check => `<li>PASS ${escape(check.name)}</li>`).join('')}</ul>${evidence.failure ? `<pre>${escape(evidence.failure.message)}</pre>` : ''}`;
    fs.writeFileSync(path.join(run, 'report.html'), report); fs.writeFileSync(path.join(OUTPUT, 'report.html'), report);
  };
  const passed = name => { evidence.checks.push({ name, status: 'pass' }); console.log('PASS ' + name); save(); };
  let child, preview, browser, failure;
  const contexts = [], violations = [], pageErrors = [], requests = [];
  save();
  try {
    const port = await freePort(), staticPort = await freePort();
    const apiOrigin = `http://127.0.0.1:${port}`, origin = `http://127.0.0.1:${staticPort}`;
    const fixtureLog = fs.openSync(path.join(run, 'fixture.log'), 'w');
    const fixtureEnv = { ...process.env, PYTHONUTF8: '1' };
    for (const key of Object.keys(fixtureEnv)) if (/SECRET|TOKEN|APIKEY|API_KEY|PASSWORD|CLOUDBASE|CLOUD_ALLOWED|TENCENTCLOUD|TENCENT_SECRET/i.test(key)) delete fixtureEnv[key];
    child = spawn(PYTHON, [path.join(ROOT, 'scripts', 'pc04_browser_fixture.py'), '--port', String(port), '--origin', origin], { cwd: ROOT, env: fixtureEnv, stdio: ['ignore', fixtureLog, fixtureLog], windowsHide: true });
    child.once('exit', () => fs.closeSync(fixtureLog));
    await readyApi(child, apiOrigin);
    const copy = prepareTestClient(apiOrigin);
    await buildClient(copy, apiOrigin, path.join(run, 'build.log'));
    preview = await staticServer(path.join(copy, 'dist'), staticPort);
    passed('Isolated test build uses FakeAuth only in ignored copy; real FastAPI loopback fixture ready');
    browser = await chromium.launch({ headless: true });
    async function actor() {
      const context = await browser.newContext({ viewport: SCREENS[1], reducedMotion: 'reduce', serviceWorkers: 'block', acceptDownloads: false });
      contexts.push(context);
      await context.tracing.start({ screenshots: true, snapshots: true });
      await context.addInitScript(installPrivacyProbe);
      await context.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url());
        if (!allowedRequest(url.href, request.method(), origin, apiOrigin, preview.staticPaths)) {
          violations.push(url.origin === apiOrigin ? 'private-or-unnamed-api' : 'external-or-static-boundary'); await route.abort(); return;
        }
        if (url.origin === apiOrigin) requests.push({ method: request.method(), route: url.pathname.replace(new RegExp(UUID, 'g'), ':id') });
        await route.continue();
      });
      const page = await context.newPage();
      page.on('pageerror', () => pageErrors.push('uncaught-browser-error'));
      return page;
    }
    const guest = await actor(), a = await actor(), b = await actor(), ops = await actor();
    const localApi = async (method, pathname, account, data, key) => {
      assert.ok(pathname.startsWith('/api/v2/'));
      assert.ok(allowedApi(method, pathname.split('?')[0]), 'Local API helper cannot call private family or role-grant paths');
      const response = await fetch(apiOrigin + pathname, { method, headers: { ...(account ? { Authorization: `Bearer community-account-${account}` } : {}),
        ...(data !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(key ? { 'Idempotency-Key': key } : {}) },
      ...(data !== undefined ? { body: JSON.stringify(data) } : {}) });
      return { response, data: response.status === 204 ? null : await response.json() };
    };

    await go(guest, origin, 'community');
    await expect(element(guest, 'pc-community-empty')).toContainText('暂时没有公开帖子');
    assert.equal(await frame(guest).locator('.pc-post-card').count(), 0);
    await expect(element(guest, 'community-real-badge')).toContainText('REAL');
    passed('REAL anonymous empty list has no synthetic fallback');
    // One definitive server failure must display a recoverable error, not fixture content.
    await guest.route(apiOrigin + '/api/v2/community/posts*', route => route.fulfill({ status: 503, contentType: 'application/json', headers: { 'Access-Control-Allow-Origin': origin }, body: JSON.stringify({ error: { code: 'service_unavailable', message: 'Synthetic unavailable', request_id: randomUUID() } }) }), { times: 1 });
    await element(guest, 'pc-feed-refresh').click();
    await expect(element(guest, 'pc-feed-error')).toBeVisible();
    assert.equal(await frame(guest).locator('.pc-post-card').count(), 0);
    await element(guest, 'pc-feed-retry').click();
    await expect(element(guest, 'pc-community-empty')).toBeVisible();
    passed('REAL failure retains error and retry without DEMO fallback');

    await go(a, origin, 'profile');
    await signIn(a, 'a');
    await saveNickname(a, '合成家长甲');
    await go(ops, origin, 'ops');
    await signIn(ops, 'c');
    await expect(element(ops, 'ops-tab-content')).toBeVisible();
    await go(b, origin, 'profile');
    await signIn(b, 'b');
    await saveNickname(b, '合成家长乙');
    passed('A and B explicitly save independent public nicknames; C server-verified operator access');

    // The remaining UI journeys are intentionally specified against semantic test IDs.
    await authorAndModerationJourneys({ a, b, ops, guest, origin, apiOrigin, localApi, passed, run, evidence });

    for (const page of [guest, a, b, ops]) {
      const probe = await page.evaluate(() => window.__pc04Probe);
      assert.deepEqual(probe, { media: 0, enumerate: 0, permissions: 0 });
    }
    assert.deepEqual(violations, []);
    assert.deepEqual(pageErrors, []);
    evidence.privacy = { external_requests: 0, private_family_requests: 0, device_requests: 0, role_grant_http: 0, browser_uncaught_errors: 0,
      api_requests: requests.length };
    passed('Community, author and protected ops workflows make zero private-family/device/external/role-grant requests');
    evidence.status = 'pass';
  } catch (error) {
    failure = error; evidence.status = 'fail'; evidence.failure = { type: error.name, message: String(error.message).slice(0, 1600) };
    save();
    for (const [index, context] of contexts.entries()) for (const [pageIndex, page] of context.pages().entries()) {
      try { await page.screenshot({ path: path.join(run, `failure-${index}-${pageIndex}.png`), fullPage: true }); } catch { /* Preserve primary failure. */ }
    }
  } finally {
    for (const [index, context] of contexts.entries()) {
      await context.tracing.stop({ path: path.join(run, `synthetic-context-${index}-trace.zip`) }).catch(() => undefined);
      await context.close().catch(() => undefined);
    }
    if (browser) await browser.close().catch(() => undefined);
    if (preview) { await preview.close(); evidence.cleanup.push('owned-static-server-closed'); }
    if (child && child.exitCode === null && child.signalCode === null) {
      const stopped = once(child, 'exit'); child.kill(); await stopped; evidence.cleanup.push('owned-memory-api-stopped');
    }
    evidence.finished_at = new Date().toISOString(); save();
  }
  if (failure) throw failure;
  console.log('PC04 local community integration PASS');
}

async function authorAndModerationJourneys({ a, b, ops, guest, origin, apiOrigin, localApi, passed, run, evidence }) {
  const owned = (page, id) => frame(page).locator(`[data-owned-id="${id}"]`);
  const publicCard = (page, id) => frame(page).locator(`[data-post-id="${id}"]`);
  async function primary(page, name) { await element(page, 'nav-' + name).click(); await waitRoute(page, name); }
  async function refreshGuest() { await element(guest, 'pc-feed-refresh').click(); }
  async function openPublic(page, id) { await element(page, 'pc-open-' + id).click(); await waitRoute(page, 'community/detail'); await expect(element(page, 'pc-real-post-body')).toBeVisible(); }
  async function moderate(id, kind, action, reason) {
    await element(ops, 'ops-tab-content').click();
    await element(ops, 'ops-kind-' + kind).click();
    await element(ops, 'ops-status-pending').click();
    await element(ops, 'ops-refresh').click();
    await element(ops, 'ops-content-' + id).click();
    await expect(element(ops, 'ops-full-body')).toBeVisible();
    await fill(ops, 'ops-reason', reason);
    await element(ops, 'ops-' + action).click();
    await expect(element(ops, 'ops-message')).toContainText('动作回执已确认');
  }
  async function enterOwnPosts(page) {
    await primary(page, 'profile');
    await element(page, 'pc-my-posts').click();
    await waitRoute(page, 'community/mine');
  }
  async function previewPost(page, title, body) {
    await fill(page, 'pc-title-input', title);
    await fill(page, 'pc-body-input', body);
    await element(page, 'pc-compose-age-6-8').click();
    await element(page, 'pc-compose-topic-parent-child').click();
    await element(page, 'pc-compose-preview').click();
    await expect(element(page, 'pc-draft-preview')).toContainText(title);
  }

  // A ordinary parent cannot retrieve ops contents. A new page uses the same in-memory auth session.
  const unauthorizedOps = await a.context().newPage();
  const unauthorizedErrors = [];
  unauthorizedOps.on('pageerror', () => unauthorizedErrors.push('uncaught-browser-error'));
  await go(unauthorizedOps, origin, 'ops');
  await signIn(unauthorizedOps, 'a');
  await expect(element(unauthorizedOps, 'ops-error')).toContainText('没有社区运营权限');
  assert.equal(await frame(unauthorizedOps).locator('[id^="ops-content-"], #ops-full-body').count(), 0);
  assert.deepEqual(unauthorizedErrors, []);
  await unauthorizedOps.close();
  passed('Ordinary authenticated parent receives ops 403 and sees no protected content');

  await primary(a, 'community');
  await element(a, 'pc-compose-entry').click();
  await waitRoute(a, 'community/compose');
  await element(a, 'pc-compose-preview').click();
  await expect(element(a, 'pc-compose-error')).toBeVisible();
  await previewPost(a, '合成分享：晚饭后聊聊天', '这是一段虚构的亲子交流记录，仅用于本地浏览器测试。');
  const attempts = [];
  a.on('request', request => {
    if (request.url() === apiOrigin + '/api/v2/community/posts' && request.method() === 'POST')
      attempts.push({ key: request.headers()['idempotency-key'], body: request.postData() });
  });
  assert.equal(attempts.length, 0, 'Local preview must not write posts');
  // Commit the initial request, then replace ONLY its acknowledgement with 503.
  // The retry must retrieve that same pending record, not create a duplicate.
  await a.route(apiOrigin + '/api/v2/community/posts', async route => {
    if (route.request().method() !== 'POST') { await route.fallback(); return; }
    const response = await route.fetch();
    assert.equal(response.status(), 201);
    await route.fulfill({ response, status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'service_unavailable', message: 'Synthetic unknown acknowledgement', request_id: randomUUID() } }) });
  }, { times: 1 });
  await element(a, 'pc-compose-submit').click();
  await expect(element(a, 'pc-compose-submit')).toHaveText('使用原操作安全重试');
  const created = await localApi('GET', '/api/v2/me/community/posts', 'a');
  assert.equal(created.response.status, 200);
  assert.equal(created.data.items.length, 1);
  const post = created.data.items[0];
  assert.equal(post.status, 'pending');
  await refreshGuest();
  await expect(element(guest, 'pc-community-empty')).toBeVisible();
  await element(a, 'pc-compose-submit').click();
  await expect(element(a, 'pc-compose-submitted')).toContainText('已提交审核，暂时不会公开展示');
  assert.equal(attempts.length, 2);
  assert.ok(attempts[0].key);
  assert.equal(attempts[0].key, attempts[1].key);
  assert.equal(attempts[0].body, attempts[1].body);
  assert.equal((await localApi('GET', '/api/v2/me/community/posts', 'a')).data.items.length, 1);
  await element(a, 'pc-compose-mine').click();
  await waitRoute(a, 'community/mine');
  await expect(owned(a, post.id)).toHaveAttribute('data-content-status', 'pending');
  passed('Preview validates input without writing; committed 503 acknowledgement safely retries same key and input without duplicates');
  await moderate(post.id, 'post', 'approve', '已检查全文，合成内容无儿童隐私。');
  await refreshGuest();
  await expect(publicCard(guest, post.id)).toBeVisible();
  await element(guest, 'pc-age-6-8').click();
  await element(guest, 'pc-topic-parent-child').click();
  await openPublic(guest, post.id);
  await expect(element(guest, 'pc-real-post-body')).toContainText('虚构的亲子交流');
  await element(guest, 'pc-detail-back').click();
  await waitRoute(guest, 'community');
  await expect(element(guest, 'pc-age-6-8')).toHaveAttribute('aria-pressed', 'true');
  await expect(element(guest, 'pc-topic-parent-child')).toHaveAttribute('aria-pressed', 'true');
  passed('Human approval makes post publicly visible; detail stack/back preserves both filters');

  await primary(b, 'community');
  await openPublic(b, post.id);
  await element(b, 'pc-comment-open').click();
  await expect(element(b, 'pc-comment-submit')).toBeEnabled();
  await fill(b, 'pc-comment-input', '字'.repeat(1001));
  await element(b, 'pc-comment-submit').click();
  await expect(element(b, 'pc-comment-message')).toBeVisible();
  await fill(b, 'pc-comment-input', '合成评论：谢谢分享，这是本地测试内容。');
  await element(b, 'pc-comment-submit').click();
  await expect(element(b, 'pc-comment-message')).toContainText('评论已提交审核');
  const comments = await localApi('GET', '/api/v2/me/community/comments', 'b');
  assert.equal(comments.data.items.length, 1);
  const comment = comments.data.items[0];
  assert.equal(comment.status, 'pending');
  assert.equal((await localApi('GET', `/api/v2/community/posts/${post.id}/comments`)).data.items.length, 0);
  await moderate(comment.id, 'comment', 'approve', '已检查一级评论，为合成测试内容。');
  await element(b, 'pc-comments-refresh').click();
  await expect(frame(b).locator(`[data-comment-id="${comment.id}"]`)).toContainText('合成家长乙');
  passed('Comment length validation prevents invalid writes; comment remains private pending until independent human approval');

  await expect(element(b, 'pc-post-like')).toBeEnabled();
  await element(b, 'pc-post-like').click();
  await expect(element(b, 'pc-post-like')).toHaveAttribute('aria-pressed', 'true');
  await element(b, 'pc-post-bookmark').click();
  await expect(element(b, 'pc-post-bookmark')).toHaveAttribute('aria-pressed', 'true');
  await b.route(apiOrigin + `/api/v2/community/posts/${post.id}/like`, route => route.fulfill({ status: 503, contentType: 'application/json', headers: { 'Access-Control-Allow-Origin': origin }, body: JSON.stringify({ error: { code: 'service_unavailable', message: 'Synthetic write failure', request_id: randomUUID() } }) }), { times: 1 });
  await element(b, 'pc-post-like').click();
  await expect(element(b, 'pc-relations-message')).toContainText('不会假设已保存');
  await element(b, 'pc-relations-retry').click();
  await expect(element(b, 'pc-post-like')).toHaveAttribute('aria-pressed', 'true');
  await element(b, 'pc-post-like').click();
  await expect(element(b, 'pc-post-like')).toHaveAttribute('aria-pressed', 'false');
  await element(b, `pc-report-post-${post.id}`).click();
  await fill(b, `pc-report-detail-post-${post.id}`, '合成隐私举报说明，仅用于测试人工核对。');
  await element(b, `pc-report-submit-post-${post.id}`).click();
  await expect(frame(b).getByText('举报已提交。', { exact: true })).toBeVisible();
  await element(ops, 'ops-tab-reports').click();
  const reportButton = frame(ops).locator('[id^="ops-report-"]').filter({ hasText: 'privacy' }).first();
  await reportButton.click();
  await fill(ops, 'ops-reason', '已人工核对；合成内容不含真实隐私，无需隐藏。');
  await element(ops, 'ops-resolve').click();
  await expect(element(ops, 'ops-message')).toContainText('内容是否隐藏需独立操作');
  const publicValue = await localApi('GET', `/api/v2/community/posts/${post.id}`);
  assert.equal(publicValue.response.status, 200, 'Resolving a report must not silently hide its target');
  assert.deepEqual(Object.keys(publicValue.data).sort(), ['age_band', 'author', 'body', 'created_at', 'id', 'published_at', 'title', 'topic', 'updated_at']);
  assert.equal((await localApi('GET', '/api/v2/me/community/bookmarks', 'b')).data.items.length, 1);
  passed('Like/bookmark use confirmed server state; failed toggle requires reread; report resolution is private and independent from hiding');

  // A stale edit may not overwrite a concurrent newer revision.
  await element(a, 'pc-mine-refresh').click();
  await expect(owned(a, post.id)).toHaveAttribute('data-content-status', 'published');
  await element(a, 'pc-mine-edit-' + post.id).click();
  await waitRoute(a, 'community/compose');
  await expect(element(a, 'pc-title-input').locator('input')).toHaveValue(post.title);
  const concurrentInput = { title: '合成分享：另一设备的新版本', body: '另一设备合成编辑，仅用于验证版本冲突。', age_band: '6-8', topic: 'parent-child', expected_revision: 1 };
  const concurrent = await localApi('PATCH', `/api/v2/community/posts/${post.id}`, 'a', concurrentInput);
  assert.equal(concurrent.response.status, 200);
  await previewPost(a, '合成分享：这个过期编辑应被阻止', '不能覆盖另一设备的更新。');
  await element(a, 'pc-compose-submit').click();
  await expect(element(a, 'pc-compose-message')).toContainText('已经变化');
  assert.equal((await localApi('GET', `/api/v2/me/community/posts/${post.id}`, 'a')).data.title, concurrentInput.title);
  assert.equal((await localApi('GET', `/api/v2/community/posts/${post.id}`)).response.status, 404);
  await element(a, 'pc-compose-edit').click();
  await element(a, 'pc-compose-reload').click();
  await expect(element(a, 'pc-title-input').locator('input')).toHaveValue(concurrentInput.title);
  await previewPost(a, '合成分享：核对后重新提交', '重新核对当前版本后再次提交，仍需人工审核。');
  await element(a, 'pc-compose-submit').click();
  await expect(element(a, 'pc-compose-submitted')).toContainText('已提交审核');
  const edited = (await localApi('GET', `/api/v2/me/community/posts/${post.id}`, 'a')).data;
  assert.equal(edited.content_revision, 3);
  assert.equal(edited.status, 'pending');
  passed('Editing published content requeues and removes old public text; stale edit is rejected without overwriting current revision');
  await moderate(post.id, 'post', 'reject', '合成审核反馈：请把经历描述得更清楚。');
  await element(a, 'pc-compose-mine').click();
  await waitRoute(a, 'community/mine');
  await expect(owned(a, post.id)).toHaveAttribute('data-content-status', 'rejected');
  await element(a, 'pc-mine-feedback-' + post.id).click();
  await expect(owned(a, post.id).locator('.pc-feedback')).toContainText('合成审核反馈');
  await element(a, 'pc-mine-edit-' + post.id).click();
  await waitRoute(a, 'community/compose');
  await expect(element(a, 'pc-title-input').locator('input')).toHaveValue(edited.title);
  await previewPost(a, '合成分享：补充交流经历', '补充说明后的虚构交流经历，供本地复审使用。');
  await element(a, 'pc-compose-submit').click();
  await expect(element(a, 'pc-compose-submitted')).toBeVisible();
  await moderate(post.id, 'post', 'approve', '合成复审已完成。');
  passed('Author receives version-matched rejection feedback and may revise and resubmit for human reapproval');

  // Refetch a hidden parent from comments and invalidate detail/actions instead of retaining stale text.
  await element(b, 'pc-comments-refresh').click();
  await expect(frame(b).locator(`[data-comment-id="${comment.id}"]`)).toBeVisible();
  await element(a, 'pc-compose-mine').click();
  await waitRoute(a, 'community/mine');
  await element(a, 'pc-mine-withdraw-' + post.id).click();
  await element(a, 'pc-mine-confirm-withdraw-' + post.id).click();
  await expect(owned(a, post.id)).toHaveAttribute('data-content-status', 'deleted');
  await element(b, 'pc-comments-refresh').click();
  await expect(element(b, 'pc-detail-missing')).toBeVisible();
  assert.equal(await frame(b).locator('#pc-post-like, #pc-post-bookmark, .pc-comment-card, #pc-real-post-body').count(), 0);
  await refreshGuest();
  await expect(element(guest, 'pc-community-empty')).toBeVisible();
  assert.equal((await localApi('GET', `/api/v2/community/posts/${post.id}/comments`)).response.status, 404);
  assert.equal((await localApi('GET', '/api/v2/me/community/bookmarks', 'b')).data.items.length, 0);
  passed('Revision-safe author withdrawal hides public post/comments, invalidates live detail and removes unavailable bookmarks');

  // Delay an old-user private result across logout, then sign into A within B's browser context.
  await primary(b, 'profile');
  let releaseOld, oldRequest;
  const oldSeen = new Promise(resolve => { oldRequest = resolve; });
  const oldRelease = new Promise(resolve => { releaseOld = resolve; });
  await b.route(apiOrigin + '/api/v2/me/community/comments*', async route => {
    const response = await route.fetch(); oldRequest(); await oldRelease; await route.fulfill({ response });
  }, { times: 1 });
  await element(b, 'pc-my-comments').click();
  await oldSeen;
  await primary(b, 'profile');
  await element(b, 'pc-community-sign-out').click();
  await expect(element(b, 'pc-community-auth')).toHaveText('未登录');
  releaseOld();
  await signIn(b, 'a');
  await element(b, 'pc-my-comments').click();
  await waitRoute(b, 'community/mine');
  await expect(element(b, 'pc-mine-empty')).toContainText('还没有本人评论');
  assert.equal(await frame(b).locator('.pc-owned-card').count(), 0);
  passed('Logout clears owned UI immediately; delayed former-user comment response cannot appear after account switch');
  await primary(b, 'profile');
  await b.route(apiOrigin + '/api/v2/me/community/posts*', route => route.fulfill({ status: 401, contentType: 'application/json', headers: { 'Access-Control-Allow-Origin': origin }, body: JSON.stringify({ error: { code: 'unauthorized', message: 'Synthetic expired identity', request_id: randomUUID() } }) }), { times: 1 });
  await element(b, 'pc-my-posts').click();
  await waitRoute(b, 'community/mine');
  await expect(element(b, 'pc-community-auth')).toHaveText('登录已失效');
  assert.equal(await frame(b).locator('.pc-owned-card').count(), 0);
  passed('401 expires shared auth and removes owned content until reauthentication');

  const hideCandidate = await localApi('POST', '/api/v2/community/posts', 'a', { title: '合成内容：独立隐藏验收', body: '用于验证运营隐藏和过期版本保护的纯合成文字。', age_band: '6-8', topic: 'parent-child' }, randomUUID());
  assert.equal(hideCandidate.response.status, 201);
  const hideId = hideCandidate.data.id;
  await moderate(hideId, 'post', 'approve', '已检查独立隐藏测试内容。');
  await refreshGuest();
  await openPublic(guest, hideId);
  await element(ops, 'ops-status-published').click();
  await element(ops, 'ops-refresh').click();
  await element(ops, 'ops-content-' + hideId).click();
  await expect(element(ops, 'ops-full-body')).toBeVisible();
  assert.equal((await localApi('PATCH', `/api/v2/community/posts/${hideId}`, 'a', { title: '合成内容：新的独立隐藏版本', body: '过期运营动作不能更改更新后的正文。', age_band: '6-8', topic: 'parent-child', expected_revision: 1 })).response.status, 200);
  await fill(ops, 'ops-reason', '这条过期版本动作必须被服务端拒绝。');
  await element(ops, 'ops-hide').click();
  await expect(element(ops, 'ops-error')).toContainText('已变化');
  assert.equal((await localApi('GET', `/api/v2/me/community/posts/${hideId}`, 'a')).data.status, 'pending');
  await moderate(hideId, 'post', 'approve', '核对当前版本后审核通过。');
  await element(ops, 'ops-status-published').click();
  await element(ops, 'ops-refresh').click();
  await element(ops, 'ops-content-' + hideId).click();
  await expect(element(ops, 'ops-full-body')).toContainText('过期运营动作');
  await fill(ops, 'ops-reason', '合成人工隐藏验收，与举报处理独立。');
  await element(ops, 'ops-hide').click();
  await expect(element(ops, 'ops-message')).toContainText('hidden');
  await element(guest, 'pc-comments-refresh').click();
  await expect(element(guest, 'pc-detail-missing')).toBeVisible();
  assert.equal((await localApi('GET', `/api/v2/community/posts/${hideId}`)).response.status, 404);
  await element(guest, 'pc-detail-back').click();
  await waitRoute(guest, 'community');
  await expect(element(guest, 'pc-community-empty')).toBeVisible();
  passed('Stale operator version receives conflict; current-version independent hide invalidates public detail and actions');

  // Populate genuine local API data using bounded synthetic principals. All 21 posts
  // are created pending and approved through normal routes; quotas remain unchanged.
  assert.equal((await localApi('PUT', '/api/v2/parent-profile', 'c', { nickname: '合成运营家长丙' })).response.status, 200);
  const fixturePosts = [];
  for (let index = 0; index < 21; index++) {
    const account = index < 10 ? 'b' : index < 20 ? 'c' : 'a';
    const result = await localApi('POST', '/api/v2/community/posts', account, { title: `合成筛选内容 ${index + 1}`, body: '纯虚构筛选与游标测试内容，无真实家庭信息。', age_band: AGES[index % 6], topic: TOPICS[index % 7] }, randomUUID());
    assert.equal(result.response.status, 201);
    const approval = await localApi('POST', `/api/v2/ops/moderation/posts/${result.data.id}/approve`, 'c', { expected_revision: 1, reason: '合成筛选数据，已检查全文。' }, randomUUID());
    assert.equal(approval.response.status, 200);
    fixturePosts.push(approval.data.content);
  }
  await element(guest, 'pc-age-all').click();
  await element(guest, 'pc-topic-all').click();
  await refreshGuest();
  await expect(frame(guest).locator('.pc-post-card')).toHaveCount(20);
  await element(guest, 'pc-feed-more').click();
  await expect(frame(guest).locator('.pc-post-card')).toHaveCount(21);
  const ids = await frame(guest).locator('.pc-post-card').evaluateAll(nodes => nodes.map(node => node.dataset.postId));
  assert.equal(new Set(ids).size, 21);
  const dates = await frame(guest).locator('.pc-post-card').evaluateAll(nodes => nodes.map(node => node.dataset.publishedAt));
  assert.deepEqual(dates, [...dates].sort().reverse());
  passed('Real cursor pages append once without duplicates in descending publication order');
  for (const age of AGES) for (const topic of TOPICS) {
    await element(guest, 'pc-age-' + age).click();
    await element(guest, 'pc-topic-' + topic).click();
    const expected = fixturePosts.filter(post => post.age_band === age && post.topic === topic).length;
    await expect(frame(guest).locator('.pc-post-card')).toHaveCount(expected);
    if (!expected) await expect(element(guest, 'pc-community-empty')).toBeVisible();
    else {
      await expect(frame(guest).locator(`.pc-post-card[data-age-band="${age}"][data-topic="${topic}"]`)).toHaveCount(expected);
      assert.deepEqual(await frame(guest).locator('.pc-post-card').evaluateAll(nodes => nodes.map(node => [node.dataset.ageBand, node.dataset.topic])), Array.from({ length: expected }, () => [age, topic]));
    }
  }
  passed('All six ages and seven topics apply AND semantics across 42 combinations, including genuine empty results');
  await element(guest, 'pc-age-all').click();
  await element(guest, 'pc-topic-all').click();

  // An in-flight protected detail must not repaint a workspace after the user
  // switches sections. Refresh the report section after network completion to
  // observe a committed render, rather than masking the race with a sleep.
  const delayedId = fixturePosts[20].id;
  await element(ops, 'ops-tab-content').click();
  await element(ops, 'ops-status-published').click();
  await element(ops, 'ops-refresh').click();
  let detailSeen, releaseDetail;
  const detailStarted = new Promise(resolve => { detailSeen = resolve; });
  const detailGate = new Promise(resolve => { releaseDetail = resolve; });
  const detailUrl = apiOrigin + `/api/v2/ops/moderation/posts/${delayedId}`;
  await ops.route(detailUrl, async route => { const response = await route.fetch(); detailSeen(); await detailGate; await route.fulfill({ response }); }, { times: 1 });
  await element(ops, 'ops-content-' + delayedId).click();
  await detailStarted;
  await element(ops, 'ops-tab-reports').click();
  const completed = Promise.all([ops.waitForResponse(response => response.url() === detailUrl), ops.waitForEvent('requestfinished', request => request.url() === detailUrl)]);
  releaseDetail(); await completed;
  await Promise.all([ops.waitForResponse(response => response.url().startsWith(apiOrigin + '/api/v2/ops/content-reports')), element(ops, 'ops-reports-refresh').click()]);
  await expect(element(ops, 'ops-tab-reports')).toHaveAttribute('aria-pressed', 'true');
  assert.equal(await frame(ops).locator('#ops-full-body').count(), 0);
  passed('Delayed protected detail cannot repaint the workspace after switching to report handling');
  await element(ops, 'ops-tab-content').click();
  await element(ops, 'ops-refresh').click();
  let refreshedDetailSeen, releaseRefreshedDetail;
  const refreshedDetailStarted = new Promise(resolve => { refreshedDetailSeen = resolve; });
  const refreshedDetailGate = new Promise(resolve => { releaseRefreshedDetail = resolve; });
  await ops.route(detailUrl, async route => { const response = await route.fetch(); refreshedDetailSeen(); await refreshedDetailGate; await route.fulfill({ response }); }, { times: 1 });
  await element(ops, 'ops-content-' + delayedId).click();
  await refreshedDetailStarted;
  await Promise.all([ops.waitForResponse(response => response.url().startsWith(apiOrigin + '/api/v2/ops/moderation?')), element(ops, 'ops-refresh').click()]);
  const refreshedDetailCompleted = Promise.all([ops.waitForResponse(response => response.url() === detailUrl), ops.waitForEvent('requestfinished', request => request.url() === detailUrl)]);
  releaseRefreshedDetail(); await refreshedDetailCompleted;
  // Observe the next committed browser render after the response, without a
  // fixed time delay or another mutating UI action that could hide stale data.
  await ops.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await frame(ops).locator('#ops-full-body').count(), 0);
  passed('Refreshing the current moderation queue also invalidates an in-flight protected detail');
  await element(ops, 'ops-content-' + delayedId).click();
  await expect(element(ops, 'ops-full-body')).toBeVisible();
  await ops.route(apiOrigin + '/api/v2/ops/moderation?*', route => route.fulfill({ status: 403, contentType: 'application/json', headers: { 'Access-Control-Allow-Origin': origin }, body: JSON.stringify({ error: { code: 'moderator_required', message: 'Synthetic access revoked', request_id: randomUUID() } }) }), { times: 1 });
  await element(ops, 'ops-refresh').click();
  await expect(element(ops, 'ops-error')).toContainText('没有社区运营权限');
  assert.equal(await frame(ops).locator('#ops-full-body, [id^="ops-content-"], [id^="ops-report-"], #ops-tab-content').count(), 0);
  passed('403 after prior authorization immediately clears protected detail, queue and report controls');
  await element(ops, 'ops-retry').click();
  await expect(element(ops, 'ops-tab-content')).toBeVisible();

  for (const screen of SCREENS) {
    await guest.setViewportSize(screen);
    await expect(element(guest, 'pc-feed-refresh')).toBeVisible();
    const dimensions = await guest.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
    assert.ok(dimensions.scroll <= dimensions.width + 1 && dimensions.body <= dimensions.width + 1, 'Horizontal overflow in REAL feed');
    for (const main of ['community', 'knowledge', 'growth', 'profile']) await expect(element(guest, 'nav-' + main)).toBeVisible();
    await element(guest, 'pc-age-6-8').focus();
    await expect(element(guest, 'pc-age-6-8')).toBeFocused();
    await element(guest, 'pc-age-6-8').press('Enter');
    await expect(element(guest, 'pc-age-6-8')).toHaveAttribute('aria-pressed', 'true');
    const shot = `real-community-${screen.width}x${screen.height}.png`;
    await guest.screenshot({ path: path.join(run, shot), fullPage: true });
    evidence.screenshots.push(shot); evidence.responsive.push({ ...screen, status: 'pass', horizontal_overflow: false, keyboard_filter: 'pass' });
  }
  for (const main of ['knowledge', 'growth', 'profile', 'community']) await primary(guest, main);
  passed('Four primary entries and seven viewport widths have clear navigation, keyboard-operable filters and no horizontal overflow');
  // Keep all fixture content withdrawn via normal revision ownership checks.
  for (let index = 0; index < fixturePosts.length; index++) {
    const account = index < 10 ? 'b' : index < 20 ? 'c' : 'a';
    assert.equal((await localApi('DELETE', `/api/v2/community/posts/${fixturePosts[index].id}?expected_revision=1`, account)).response.status, 204);
  }
  await refreshGuest();
  await expect(element(guest, 'pc-community-empty')).toBeVisible();
  passed('Synthetic publication fixtures are withdrawn; no posts remain public after local acceptance');
}

if (require.main === module) acceptance().catch(error => { console.error(error); process.exitCode = 1; });
module.exports = { allowedApi, allowedRequest, prepareTestClient, staticServer, installPrivacyProbe };
