/** Real official-SDK H5 acceptance. Private credentials arrive only on stdin. */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');

const ROOT = path.resolve(__dirname, '..');
const DIST = path.join(ROOT, 'apps', 'client', 'dist');
const ORIGIN = 'http://127.0.0.1:18404';
const ENV_ID = 'soulcompanion-dev-d0dzo6f2a24211';
const CLOUD_ORIGIN = `https://${ENV_ID}.api.tcloudbasegateway.com`;
const API_ORIGIN = `https://${ENV_ID}-1501181209.ap-shanghai.app.tcloudbase.com`;
const API_BASE = API_ORIGIN + '/api/v2';
const checks = {};
let stage = 'initialization';

function check(name, condition) {
  if (!condition) throw new Error('BROWSER_ASSERTION_FAILED');
  checks[name] = true;
}
const element = (page, id) => page.locator(`[data-testid="${id}"]:visible, #${id}:visible`).first();
const input = (page, id) => page.locator(`#${id} input, input#${id}`).first();
const forbiddenKeys = new Set(['owner_user_id', 'uid', 'openid', 'device_id', 'device_label',
  'camera_frame', 'audio_chunk', 'frames', 'raw_audio', 'raw_image', 'media', 'session_key']);
function metadataOnly(value) {
  if (Array.isArray(value)) return value.every(metadataOnly);
  if (!value || typeof value !== 'object') return true;
  return Object.entries(value).every(([key, item]) => !forbiddenKeys.has(key.toLowerCase()) && metadataOnly(item));
}
function approvedUrl(url) {
  const parsed = new URL(url);
  return !parsed.username && !parsed.password && [ORIGIN, CLOUD_ORIGIN, API_ORIGIN].includes(parsed.origin);
}

async function serve() {
  const dist = fs.realpathSync(DIST);
  const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png',
    '.json': 'application/json', '.woff': 'font/woff', '.woff2': 'font/woff2' };
  const server = http.createServer((request, response) => {
    try {
      if (!['GET', 'HEAD'].includes(request.method)) { response.writeHead(405).end(); return; }
      const url = new URL(request.url, ORIGIN);
      const filename = path.resolve(dist, '.' + decodeURIComponent(url.pathname));
      if (!filename.startsWith(dist + path.sep) && filename !== dist) throw new Error('BOUNDARY');
      let target = filename;
      if (fs.existsSync(target) && fs.statSync(target).isDirectory()) target = path.join(target, 'index.html');
      if (!fs.existsSync(target) && !path.extname(target)) target = path.join(dist, 'index.html');
      const real = fs.realpathSync(target);
      if (!real.startsWith(dist + path.sep) || !fs.statSync(real).isFile()) throw new Error('BOUNDARY');
      response.writeHead(200, { 'Content-Type': types[path.extname(real)] || 'application/octet-stream',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
      if (request.method === 'HEAD') { response.end(); return; }
      const stream = fs.createReadStream(real);
      stream.once('error', () => response.destroy());
      stream.pipe(response);
    } catch { response.writeHead(404).end(); }
  });
  server.on('clientError', (_, socket) => socket.destroy());
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    // Never reuse an unknown existing server on this CORS-allowed fixture port.
    server.listen(18404, '127.0.0.1', resolve);
  });
  return server;
}

async function tokenDenied(token) {
  for (let attempt = 0; attempt < 5; attempt++) {
    const response = await fetch(API_BASE + '/me', { headers: { Authorization: `Bearer ${token}` },
      redirect: 'error', signal: AbortSignal.timeout(12000) });
    if (response.status !== 429) return response.status === 401;
    const header = response.headers.get('retry-after') || '';
    const wait = /^\d+(?:\.\d+)?$/.test(header) ? Number(header) : 2 ** attempt;
    if (attempt < 4) await new Promise(resolve => setTimeout(resolve, Math.min(60, Math.max(0.1, wait)) * 1000));
  }
  return false;
}

async function acceptance() {
  const { chromium, expect } = require('@playwright/test');
  const credentials = JSON.parse(fs.readFileSync(0, 'utf8'));
  if (!credentials || typeof credentials.username !== 'string' || typeof credentials.password !== 'string'
    || !/^scphase04_[a-f0-9]{20}$/.test(credentials.username) || credentials.password.length > 32) {
    throw new Error('PRIVATE_INPUT_INVALID');
  }
  let server, browser;
  try {
    stage = 'static_fixture';
    server = await serve();
    browser = await chromium.launch({ headless: true });
    // There is deliberately no trace, video, screenshot, HAR or console capture.
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addInitScript(() => {
      window.__cloudAcceptance = { mediaCalls: 0, storageWrites: [] };
      if (navigator.mediaDevices?.getUserMedia) {
        const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
        navigator.mediaDevices.getUserMedia = (...args) => {
          window.__cloudAcceptance.mediaCalls++;
          return original(...args);
        };
      }
      const original = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) {
        // Values stay in browser memory and are inspected only for booleans.
        window.__cloudAcceptance.storageWrites.push([String(key), String(value)]);
        return original.call(this, key, value);
      };
    });
    const page = await context.newPage();
    page.setDefaultTimeout(45000);
    let guest = true, guestPrivate = 0, privateRequests = 0, mediaSafe = true;
    let latestToken = '', meLoaded = false, deniedHost = false;
    const privateTokens = new Set();
    const privateResponseReads = new Set();
    await context.route('**/*', async route => {
      if (!approvedUrl(route.request().url())) { deniedHost = true; await route.abort(); return; }
      await route.continue();
    });
    page.on('request', request => {
      const url = new URL(request.url());
      if (url.origin !== API_ORIGIN || !url.pathname.startsWith('/api/v2/')) return;
      if (['/api/v2/healthz', '/api/v2/readyz'].includes(url.pathname)) return;
      privateRequests++;
      if (guest) guestPrivate++;
      const authorization = request.headers().authorization || '';
      if (authorization.startsWith('Bearer ')) {
        latestToken = authorization.slice(7);
        privateTokens.add(latestToken);
      }
      const raw = request.postData();
      if (raw) {
        try { mediaSafe &&= metadataOnly(JSON.parse(raw)); } catch { mediaSafe = false; }
      }
      const type = request.headers()['content-type'] || '';
      if (/^(?:image\/|audio\/|video\/|multipart\/|application\/octet-stream)/i.test(type)) mediaSafe = false;
    });
    page.on('response', response => {
      if (response.url() === API_BASE + '/me' && response.status() === 200) meLoaded = true;
      const url = new URL(response.url());
      if (url.origin === CLOUD_ORIGIN && url.pathname.startsWith('/auth/v1/') && response.status() === 200) {
        const inspect = value => {
          if (!value || typeof value !== 'object') return;
          for (const [key, item] of Object.entries(value)) {
            if (/^(?:access_token|refresh_token|session_key|sessionKey)$/.test(key) && typeof item === 'string' && item) privateTokens.add(item);
            else if (item && typeof item === 'object') inspect(item);
          }
        };
        // Reading official auth responses here only retains opaque secrets in
        // memory, to detect plain-value persistence as well as JSON sessions.
        const read = response.json().then(inspect).catch(() => undefined);
        privateResponseReads.add(read);
        void read.finally(() => privateResponseReads.delete(read));
      }
    });
    stage = 'guest_boundary';
    await page.goto(ORIGIN, { waitUntil: 'domcontentloaded' });
    await element(page, 'nav-profile').click();
    await expect(element(page, 'pc-account-status')).toContainText('未登录');
    await element(page, 'pc-private-account').click();
    await expect(element(page, 'cloud-auth-status')).toContainText('未登录');
    check('guest_private_requests_absent', guestPrivate === 0);
    check('automatic_device_acquisition_absent', await page.evaluate(() => window.__cloudAcceptance.mediaCalls === 0));
    stage = 'official_sdk_login';
    await input(page, 'cloud-username').fill(credentials.username);
    await input(page, 'cloud-password').fill(credentials.password);
    guest = false;
    await element(page, 'cloud-sign-in').click();
    await expect(element(page, 'cloud-auth-status')).toContainText('已登录');
    await expect(element(page, 'cloud-profile-empty')).toBeVisible();
    check('official_sdk_login', Boolean(latestToken) && !deniedHost);
    check('me_ui_loaded', meLoaded && await element(page, 'cloud-display-name').isVisible());
    stage = 'profile_lifecycle';
    const initial = 'Synthetic browser fixture';
    const renamed = 'Synthetic browser renamed fixture';
    await input(page, 'cloud-profile-nickname').fill(initial);
    await element(page, 'cloud-profile-save').click();
    await expect(element(page, 'cloud-profile-select-0')).toContainText(initial);
    check('profile_created', true);
    await element(page, 'cloud-profile-edit-0').click();
    await input(page, 'cloud-profile-nickname').fill(renamed);
    await element(page, 'cloud-profile-save').click();
    await expect(element(page, 'cloud-profile-select-0')).toContainText(renamed);
    check('profile_renamed', true);
    await element(page, 'cloud-profile-select-0').click();
    await expect(element(page, 'cloud-profile-select-0')).toContainText('已选择');
    check('profile_selected', true);
    // Selection has three private reads; waiting for the archive action to be
    // enabled observes the state transition instead of hiding it with a sleep.
    await expect(element(page, 'cloud-profile-archive-0')).not.toHaveAttribute('aria-disabled', 'true');
    await element(page, 'cloud-profile-archive-0').click();
    await expect(element(page, 'cloud-profile-empty')).toBeVisible();
    check('profile_archived', true);
    stage = 'logout_boundary';
    // Context cookies also include HttpOnly cookies that document.cookie cannot
    // inspect. Keep snapshots only in memory, including while signed in.
    const signedInCookies = await context.cookies();
    const signedInToken = latestToken;
    await element(page, 'cloud-sign-out').click();
    await expect(element(page, 'cloud-auth-status')).toContainText('未登录');
    await expect(element(page, 'cloud-profile-list')).toHaveCount(0);
    await expect(element(page, 'cloud-display-name')).toHaveCount(0);
    check('logout_hides_private_data', true);
    // The UI clears immediately. The network response proves revocation has
    // completed; a predicate poll handles its legitimate asynchronous path.
    await expect.poll(() => tokenDenied(signedInToken), { timeout: 90000 }).toBe(true);
    check('token_revoked', true);
    await Promise.all(privateResponseReads);
    const privateStorageAbsent = await page.evaluate(({ tokens, password }) => {
      const entries = [...Object.entries(localStorage), ...Object.entries(sessionStorage),
        ...window.__cloudAcceptance.storageWrites];
      return entries.every(([key, value]) => !/(?:access.?token|refresh.?token|session.?key)/i.test(key)
        && tokens.every(token => !value.includes(token)) && !value.includes(password)
        && !/"(?:access_token|refresh_token|session_key|sessionKey)"\s*:/i.test(value))
        && tokens.every(token => !document.cookie.includes(token))
        && !document.cookie.includes(password)
        && !/(?:access_token|refresh_token|session_key|sessionKey)=/i.test(document.cookie);
    }, { tokens: [...privateTokens], password: credentials.password });
    const cookies = [...signedInCookies, ...await context.cookies()];
    const privateCookiesAbsent = cookies.every(cookie => {
      let value = cookie.value;
      try { value = decodeURIComponent(value); } catch { /* Inspect the original malformed value. */ }
      return !/(?:access.?token|refresh.?token|session)/i.test(cookie.name)
        && [...privateTokens].every(token => !value.includes(token))
        && !value.includes(credentials.password)
        && !/"(?:access_token|refresh_token|session_key|sessionKey)"\s*:/i.test(value);
    });
    check('auth_storage_absent', privateStorageAbsent && privateCookiesAbsent);
    check('raw_media_requests_absent', privateRequests > 0 && mediaSafe);
    check('automatic_device_acquisition_absent', await page.evaluate(() => window.__cloudAcceptance.mediaCalls === 0));
    stage = 'complete';
    return { status: 'pass', checks };
  } finally {
    credentials.password = '';
    if (browser) await browser.close();
    if (server) await new Promise(resolve => {
      server.close(resolve);
      server.closeAllConnections();
    });
  }
}

if (!process.argv.includes('--apply')) {
  process.stdout.write(JSON.stringify({ status: 'plan', real_calls: false, origin: ORIGIN,
    api_base_url: API_BASE, credential_input: 'private stdin only' }) + '\n');
} else {
  acceptance().then(result => process.stdout.write(JSON.stringify(result) + '\n')).catch(() => {
    // Browser errors can quote input values, request bodies, URLs or headers.
    process.stdout.write(JSON.stringify({ status: 'failed', stage, checks,
      code: 'BROWSER_ACCEPTANCE_FAILED' }) + '\n');
    process.exitCode = 1;
  });
}
