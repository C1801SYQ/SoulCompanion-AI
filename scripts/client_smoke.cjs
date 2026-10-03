/** Phase02 H5 acceptance: actual local V1 API, synthetic SQLite, no media capture. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { randomUUID } = require('node:crypto');
const { chromium, expect } = require('@playwright/test');

const ROOT = path.resolve(__dirname, '..');
const DIST = path.join(ROOT, 'apps', 'client', 'dist');
const OUTPUT = path.join(ROOT, '.test-artifacts', 'v2-client-acceptance');
const PYTHON = process.env.SOULCOMPANION_PYTHON || 'python';
const DEMO_ONLY = process.argv.includes('--demo-only');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const exited = child => child.exitCode !== null || child.signalCode !== null;
const apiPaths = new Set([
  '/api/v1/dashboard/snapshot', '/api/v1/emotions/history', '/api/v1/emotions/analytics',
  '/api/v1/reports/parent', '/api/v1/reports/parent.md', '/api/v1/system/status',
  '/api/v1/system/settings', '/api/v1/system/readiness',
]);

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

async function refused(port) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const closed = await new Promise((resolve, reject) => {
      const socket = net.createConnection({ host: '127.0.0.1', port });
      socket.once('connect', () => { socket.destroy(); resolve(false); });
      socket.once('error', error => {
        socket.destroy();
        if (error.code === 'ECONNREFUSED') resolve(true);
        else reject(error);
      });
      // Windows refusal can take about two seconds. A timeout is inconclusive.
      socket.setTimeout(Math.min(3000, Math.max(1, deadline - Date.now())), () => { socket.destroy(); resolve(false); });
    });
    if (closed) return;
    await pause(100);
  }
  throw new Error(`Owned fixture TCP port ${port} did not give ECONNREFUSED`);
}

/** Test-only same-origin proxy. It is never installed in the production API. */
async function previewWorker() {
  const args = process.argv.slice(3);
  const arg = name => args[args.indexOf(name) + 1];
  const port = Number(arg('--port'));
  const upstreamPort = Number(arg('--upstream-port'));
  const stopFile = arg('--stop-file');
  assert.ok(Number.isInteger(port) && port > 0 && port < 65536);
  assert.ok(Number.isInteger(upstreamPort) && upstreamPort > 0 && upstreamPort < 65536);
  assert.ok(stopFile && path.resolve(stopFile).startsWith(OUTPUT + path.sep));
  const realDist = fs.realpathSync(DIST);
  const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2', '.woff': 'font/woff' };
  const server = http.createServer((request, response) => {
    let url;
    try { url = new URL(request.url, `http://127.0.0.1:${port}`); } catch { response.writeHead(400); response.end(); return; }
    if (request.method !== 'GET' && request.method !== 'HEAD') { response.writeHead(405); response.end(); return; }
    if (url.pathname.startsWith('/api/')) {
      if (!apiPaths.has(url.pathname) || request.method !== 'GET') { response.writeHead(404); response.end(); return; }
      // Only named read-only fixture endpoints and the fixed loopback destination.
      // Drop client forwarding/cookie headers; make Host/Origin match the fixture.
      const upstream = http.request({ hostname: '127.0.0.1', port: upstreamPort,
        path: url.pathname + url.search, method: 'GET', agent: false,
        headers: { Host: `127.0.0.1:${upstreamPort}`, Origin: `http://127.0.0.1:${upstreamPort}`,
          Accept: request.headers.accept || 'application/json', 'Sec-Fetch-Site': 'same-origin' },
      }, incoming => {
        response.writeHead(incoming.statusCode, incoming.headers);
        incoming.pipe(response);
        incoming.once('error', error => response.destroy(error));
      });
      upstream.setTimeout(7000, () => upstream.destroy(new Error('Fixture proxy upstream timed out')));
      upstream.once('error', () => response.destroy());
      response.once('close', () => { if (!response.writableFinished) upstream.destroy(); });
      upstream.end();
      return;
    }
    let filename;
    try {
      filename = path.resolve(realDist, '.' + decodeURIComponent(url.pathname));
      if (filename !== realDist && !filename.startsWith(realDist + path.sep)) throw new Error('Path boundary');
      if (fs.existsSync(filename) && fs.statSync(filename).isDirectory()) filename = path.join(filename, 'index.html');
      if (!fs.existsSync(filename) && !path.extname(filename)) filename = path.join(realDist, 'index.html');
      const realFile = fs.realpathSync(filename);
      if (!realFile.startsWith(realDist + path.sep) || !fs.statSync(realFile).isFile()) throw new Error('File boundary');
      response.writeHead(200, { 'Content-Type': types[path.extname(realFile)] || 'application/octet-stream',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
      if (request.method === 'HEAD') { response.end(); return; }
      const stream = fs.createReadStream(realFile);
      stream.once('error', error => response.destroy(error));
      stream.pipe(response);
    } catch { response.writeHead(404); response.end('Not found'); }
  });
  server.on('clientError', (_, socket) => socket.destroy());
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
  const watcher = setInterval(() => {
    if (!fs.existsSync(stopFile)) return;
    clearInterval(watcher);
    server.close(error => { if (error) { console.error(error); process.exitCode = 1; } });
    server.closeIdleConnections();
  }, 50);
}

const element = (page, id) => page.locator(`[data-testid="${id}"]:visible, #${id}:visible`).first();

async function acceptance() {
  fs.mkdirSync(OUTPUT, { recursive: true });
  const run = fs.mkdtempSync(path.join(OUTPUT, 'run-'));
  const evidence = { status: 'running', build_mode: DEMO_ONLY ? 'demo-only' : 'real-capable', started_at: new Date().toISOString(),
    fixture: 'Actual FastAPI/V1 and isolated synthetic 65-record SQLite; no hardware or media inference',
    run_directory: run, checks: [], screenshots: [], responsive: [], cleanup: [], api_requests: [], limitations: [
      'Phase02 H5 UI only; camera/microphone capture, cloud authentication, WeChat and Android are later stages',
      'Basic DOM/keyboard/motion checks do not establish full WCAG or screen-reader conformance',
    ] };
  const resultsPath = path.join(OUTPUT, 'results.json');
  const save = () => {
    const json = JSON.stringify(evidence, null, 2) + '\n';
    fs.writeFileSync(path.join(run, 'results.json'), json);
    fs.writeFileSync(resultsPath, json);
  };
  save();
  const children = new Set();
  let browser, failure, checksComplete = false;
  const database = path.join(run, 'synthetic.sqlite');
  let backendPort, previewPort;

  async function stop(child) {
    if (!child || !children.has(child)) return;
    if (!child.pid) { children.delete(child); return; }
    if (!exited(child)) {
      const closed = new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`${child.fixtureName} did not exit after private stop signal`)), 10000);
        child.once('exit', () => { clearTimeout(timer); resolve(); });
      });
      if (!fs.existsSync(child.stopFile)) fs.writeFileSync(child.stopFile, 'stop', { flag: 'wx' });
      await closed;
    }
    assert.equal(child.exitCode, 0, `${child.fixtureName} exited unsuccessfully`);
    await refused(child.fixturePort);
    fs.rmSync(child.stopFile, { force: true });
    children.delete(child);
    evidence.cleanup.push({ server: child.fixtureName, port: child.fixturePort, graceful_exit: true, tcp_refused: true });
  }

  async function start(command, args, port, readyPath, name) {
    const stopFile = path.join(run, 'stop-' + randomUUID() + '.signal');
    const log = fs.openSync(path.join(run, name + '.log'), 'a');
    const child = spawn(command, [...args, '--stop-file', stopFile], { cwd: ROOT, windowsHide: true,
      env: { ...process.env, PYTHONUTF8: '1' }, stdio: ['ignore', log, log] });
    fs.closeSync(log);
    Object.assign(child, { stopFile, fixturePort: port, fixtureName: name });
    children.add(child);
    let spawnError;
    child.on('error', error => { spawnError = error; });
    for (let i = 0; i < 100; i++) {
      if (spawnError) throw spawnError;
      if (exited(child)) throw new Error(`${name} exited before ready; see ${name}.log`);
      try { if ((await fetch(`http://127.0.0.1:${port}${readyPath}`, { signal: AbortSignal.timeout(700) })).ok) return child; } catch { /* Owned fixture is still starting. */ }
      await pause(100);
    }
    throw new Error(`${name} did not become ready`);
  }

  function passed(name, details = {}) {
    evidence.checks.push({ name, status: 'passed', ...details });
    process.stdout.write(`PASS ${name}\n`);
    save();
  }

  async function screenshot(page, name, fullPage = false) {
    const filename = path.join(run, name + '.png');
    await page.screenshot({ path: filename, fullPage, animations: 'disabled' });
    evidence.screenshots.push(filename);
  }

  async function navigate(page, name) {
    await element(page, 'nav-' + name).click();
    await expect(page).toHaveURL(new RegExp(`(?:/pages/)?${name}(?:/index)?(?:[/?]|$)`));
    await expect(element(page, 'nav-' + name)).toHaveAttribute('aria-current', 'page');
  }

  async function historyResponse(page, action, days, offset = 0) {
    const incoming = page.waitForResponse(response => {
      const url = new URL(response.url());
      return url.pathname === '/api/v1/emotions/history' && url.searchParams.get('days') === String(days)
        && Number(url.searchParams.get('offset') || 0) === offset && response.status() === 200;
    });
    await action();
    const wire = await (await incoming).json();
    assert.equal(wire.mode, 'real'); assert.equal(wire.total, 65); assert.equal(wire.offset, offset);
    return wire;
  }

  async function reportDownload(page, filename, keyboard = false) {
    const incoming = page.waitForEvent('download');
    if (keyboard) {
      await expect(page.getByRole('button', { name: /导出\s*Markdown/ })).toHaveCount(1);
      await expect(element(page, 'report-export')).toBeEnabled({ timeout: 20000 });
      await element(page, 'report-export').focus();
      await page.keyboard.press('Space');
    } else await element(page, 'report-export').click();
    const download = await incoming;
    assert.equal(await download.failure(), null);
    const target = path.join(run, filename);
    await download.saveAs(target);
    evidence.downloads ||= [];
    evidence.downloads.push({ filename: target, suggested_name: download.suggestedFilename() });
    return fs.readFileSync(target, 'utf8');
  }

  async function checkLayouts(page) {
    for (const width of [375, 390, 430, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: width < 600 ? 844 : 900 });
      for (const name of ['home', 'session', 'insights', 'reports', 'settings']) {
        if (name !== 'home' || !page.url().includes('/home')) await navigate(page, name);
        if (DEMO_ONLY) await expect(element(page, 'demo-badge')).toBeVisible();
        else await expect(element(page, 'connection-status')).toContainText(/已连接|online/i, { timeout: 15000 });
        await pause(100);
        const layout = await page.evaluate(() => ({
          viewport: innerWidth, documentWidth: document.documentElement.scrollWidth,
          areas: [...document.querySelectorAll('.sc-shell,.sc-main')].map(node => ({
            className: node.className, contentWidth: node.scrollWidth, clientWidth: node.clientWidth,
          })),
        }));
        assert.ok(layout.documentWidth <= width + 1, `${name} document overflows at ${width}px`);
        layout.areas.forEach(area => assert.ok(area.contentWidth <= area.clientWidth + 1, `${name} ${area.className} overflows at ${width}px`));
        evidence.responsive.push({ page: name, width, ...layout });
        if ((width === 1440 && ['session', 'reports', 'settings'].includes(name))
          || (width === 390 && ['session', 'insights'].includes(name))) await screenshot(page, `${name}-${width}`, true);
      }
      await navigate(page, 'home');
      if (width === 390 || width === 1440) {
        const headings = await page.locator('.sc-section-heading').evaluateAll(nodes => {
          const bounds = node => {
            const box = node.getBoundingClientRect();
            const style = getComputedStyle(node);
            return { x: box.x, y: box.y, right: box.right, bottom: box.bottom, width: box.width, height: box.height,
              visible: node.getClientRects().length > 0 && style.visibility !== 'hidden' && style.display !== 'none' };
          };
          const rgba = value => {
            const values = value.match(/[\d.]+/g)?.map(Number);
            if (!/^rgba?\(/.test(value) || !values || values.length < 3) throw new Error(`Unsupported computed color: ${value}`);
            return [...values.slice(0, 3), values[3] ?? 1];
          };
          const paint = (foreground, background) => foreground.slice(0, 3).map((channel, index) =>
            channel * foreground[3] + background[index] * (1 - foreground[3]));
          const luminance = color => color.map(channel => {
            const normalized = channel / 255;
            return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
          }).reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
          return nodes.map(node => {
            const action = node.querySelector('.sc-text-action');
            const textBounds = [];
            const walker = document.createTreeWalker(action, NodeFilter.SHOW_TEXT);
            let text;
            while ((text = walker.nextNode())) {
              if (!text.textContent.trim()) continue;
              const range = document.createRange();
              range.selectNodeContents(text);
              const box = range.getBoundingClientRect();
              textBounds.push({ text: text.textContent, x: box.x, y: box.y, right: box.right, bottom: box.bottom,
                width: box.width, height: box.height });
            }
            const style = getComputedStyle(action);
            const ancestry = [];
            for (let parent = action; parent; parent = parent.parentElement) ancestry.push(parent);
            let background = [255, 255, 255];
            for (const parent of ancestry.reverse()) background = paint(rgba(getComputedStyle(parent).backgroundColor), background);
            const foreground = rgba(style.color);
            foreground[3] *= Number(style.opacity);
            const light = [luminance(paint(foreground, background)), luminance(background)].sort((a, b) => a - b);
            return { heading: bounds(node), labels: bounds(node.querySelector('.sc-section-labels')),
              title: node.querySelector('.sc-section-title').textContent, action: bounds(action),
              action_text: action.textContent.trim(), action_text_bounds: textBounds,
              action_attributes: { disabled: action.getAttribute('disabled'), aria_disabled: action.getAttribute('aria-disabled') },
              action_style: { color: style.color, fontSize: style.fontSize, opacity: style.opacity, overflow: style.overflow,
                background_rgb: background, text_contrast: (light[1] + 0.05) / (light[0] + 0.05) } };
          });
        });
        evidence.section_headings ||= [];
        evidence.section_headings.push({ width, sections: headings });
        assert.equal(headings.length, 2, 'Home must retain both report/history section headings');
        for (const section of headings) {
          assert.ok(section.labels.visible && section.action.visible && section.labels.height > 0 && section.action.height > 0,
            `${section.title} heading and action must render visibly at ${width}px`);
          assert.ok(section.labels.width >= 120 && section.action.width < section.labels.width,
            `${section.title} heading must not be squeezed by a full-width action at ${width}px`);
          assert.ok(section.labels.right <= section.action.x + 1 && section.labels.x >= section.heading.x - 1
            && section.action.right <= section.heading.right + 1 && section.heading.right <= width + 1,
          `${section.title} heading and action must fit without overlap at ${width}px`);
          assert.match(section.action_text, /查看报告|全部记录/);
          assert.equal(section.action_attributes.disabled, null, `${section.title} enabled action must omit the native disabled attribute`);
          assert.equal(section.action_attributes.aria_disabled, 'false');
          assert.ok(section.action_style.text_contrast >= 4.5, `${section.title} enabled action text must contrast with its actual background at ${width}px`);
          assert.ok(section.action_text_bounds.some(box => box.width > 0 && box.height > 0
            && box.x >= section.action.x - 1 && box.right <= section.action.right + 1
            && box.y >= section.action.y - 1 && box.bottom <= section.action.bottom + 1),
          `${section.title} action text must render inside its actual button at ${width}px`);
        }
        for (let index = 0; index < headings.length; index++) {
          const heading = page.locator('.sc-section-heading').nth(index);
          await heading.evaluate(node => node.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' }));
          const uncovered = await heading.locator('.sc-text-action').evaluate(node => {
            const box = node.getBoundingClientRect();
            const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
            return Boolean(hit && (hit === node || node.contains(hit)));
          });
          assert.ok(uncovered, `${headings[index].title} action must be uncovered in its screenshot at ${width}px`);
          await screenshot(page, `home-section-heading-${width}-${index + 1}`);
        }
        await page.locator('.sc-home-heading').scrollIntoViewIfNeeded();
      }
      if (width < 600) {
        const action = await element(page, 'start-session').boundingBox();
        assert.ok(action && action.y >= 0 && action.y + action.height <= 845, `Start Session must be visible in the ${width}px first screen`);
      }
      await screenshot(page, `home-${width}`);
    }
    passed('All five pages have no page overflow at 375/390/430/768/1024/1440px');
  }

  try {
    backendPort = await freePort();
    previewPort = await freePort();
    const base = `http://127.0.0.1:${previewPort}`;
    assert.ok(fs.existsSync(path.join(DIST, 'index.html')), 'Build apps/client/dist before running H5 acceptance');
    let backend = await start(PYTHON, ['scripts/acceptance_server.py', '--port', String(backendPort), '--db', database, '--seed'], backendPort, '/healthz', 'backend');
    await start(process.execPath, [__filename, '--preview-worker', '--port', String(previewPort), '--upstream-port', String(backendPort)], previewPort, '/', 'preview');
    assert.equal((await fetch(base + '/api/unknown')).status, 404);
    assert.equal((await fetch(base + '/api/v1/dashboard/snapshot', { method: 'POST' })).status, 405);
    const guarded = await fetch(`http://127.0.0.1:${backendPort}/api/v1/dashboard/snapshot`, {
      headers: { Forwarded: 'for=198.51.100.1' },
    });
    assert.equal(guarded.status, 403);
    assert.equal((await guarded.json()).error.code, 'LOCAL_ACCESS_ONLY');
    passed('Read-only named test proxy works without weakening the actual local-only FastAPI boundary');
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce', acceptDownloads: true });
    let mediaRequests = 0;
    await context.exposeBinding('__scCaptureAttempt', () => { mediaRequests += 1; });
    await context.addInitScript(() => {
      window.__scMediaRequests = 0;
      const media = navigator.mediaDevices;
      window.__scMediaAvailable = Boolean(media && typeof media.getUserMedia === 'function');
      if (media) Object.defineProperty(media, 'getUserMedia', { configurable: true, value: async () => {
        window.__scMediaRequests += 1;
        await window.__scCaptureAttempt();
        throw new Error('Phase02 must not request media devices');
      } });
    });
    const page = await context.newPage();
    const fatal = [], consoleErrors = [], expectedRenderExceptions = [];
    evidence.fatal_errors = fatal;
    evidence.console_errors = consoleErrors;
    evidence.expected_render_exceptions = expectedRenderExceptions;
    let expectedRenderFailure = false;
    page.on('pageerror', error => {
      if (expectedRenderFailure && error.message.includes('private-render-marker')) expectedRenderExceptions.push(error.message);
      else fatal.push(error.message);
    });
    page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
    page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/')) evidence.api_requests.push(request.url()); });
    await page.goto(base, { waitUntil: 'domcontentloaded' });
    if (DEMO_ONLY) {
      await expect(element(page, 'demo-badge')).toBeVisible();
      await expect(element(page, 'connection-status')).toHaveCount(0);
      await expect(page.getByRole('main')).toHaveCount(1);
      await expect(page.getByRole('navigation', { name: '主要导航' })).toHaveCount(1);
      await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
      await checkLayouts(page);
      await navigate(page, 'settings');
      await expect(element(page, 'mode-real')).toBeDisabled();
      await expect(element(page, 'mode-demo')).toHaveAttribute('aria-pressed', 'true');
      await navigate(page, 'session');
      await expect(element(page, 'camera-status')).toContainText(/OFF|关闭|未开启/i);
      await expect(element(page, 'microphone-status')).toContainText(/OFF|关闭|未开启/i);
      await navigate(page, 'reports');
      assert.match(await reportDownload(page, 'parent-demo-only.md'), /DEMO DATA|合成演示数据/);
      await pause(2200);
      assert.deepEqual(evidence.api_requests, [], 'A compiled DEMO_ONLY build must make zero API requests even with a real fixture running');
      assert.equal(mediaRequests, 0);
      assert.equal(await page.evaluate(() => window.__scMediaRequests), 0);
      assert.deepEqual(fatal, []);
      assert.deepEqual(consoleErrors, []);
      evidence.fatal_errors = fatal;
      evidence.console_errors = consoleErrors;
      evidence.media_permission_requests = mediaRequests;
      passed('Compiled DEMO_ONLY stays synthetic on every page, disables REAL, exports labelled report and never calls API/media');
    } else {
    await expect(element(page, 'connection-status')).toContainText(/已连接|online/i, { timeout: 20000 });
    await expect(element(page, 'emotion-label')).toContainText(/暂无|等待|尚无|未观测/);
    await expect(element(page, 'confidence-value')).toHaveText(/^(置信度\s*)?(--|—|暂无数据|未观测)$/);
    assert.equal(await page.evaluate(() => window.__scMediaAvailable), true, 'Chromium loopback fixture must expose the genuine media API for this check');
    assert.equal(await page.evaluate(() => window.__scMediaRequests), 0);
    assert.equal(mediaRequests, 0);
    assert.deepEqual(fatal, []);
    assert.deepEqual(consoleErrors, [], 'Initial REAL render must have no console errors before deliberate failure scenarios');
    await screenshot(page, 'initial-real');
    await expect(page.getByRole('main')).toHaveCount(1);
    await expect(page.getByRole('navigation', { name: '主要导航' })).toHaveCount(1);
    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
    await expect(page.getByRole('button', { name: /首页/ })).toHaveCount(1);
    passed('Actual REAL V1 snapshot renders unavailable live emotion and null confidence; no media permission request');

    evidence.visibility_lifecycle = { stimulus: 'Simulated document visibilitychange in actual H5; not an OS-background or lock-screen test' };
    const originalVisibility = await page.evaluate(() => document.visibilityState);
    assert.equal(originalVisibility, 'visible');
    try {
      await page.evaluate(() => {
        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
        Object.defineProperty(document, 'hidden', { configurable: true, value: true });
        document.dispatchEvent(new Event('visibilitychange', { bubbles: true }));
      });
      await pause(500);
      const hiddenStart = evidence.api_requests.length;
      await pause(3200);
      assert.equal(evidence.api_requests.length, hiddenStart, 'Hidden H5 page must stop all polling, not just delay its results');
      evidence.visibility_lifecycle.hidden_observation_ms = 3200;
      evidence.visibility_lifecycle.hidden_api_requests = 0;
    } finally {
      const resumed = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/dashboard/snapshot' && response.status() === 200);
      await page.evaluate(() => {
        delete document.visibilityState;
        delete document.hidden;
        document.dispatchEvent(new Event('visibilitychange', { bubbles: true }));
      });
      const wire = await (await resumed).json();
      assert.equal(wire.mode, 'real');
      assert.equal(wire.emotion, null);
      evidence.visibility_lifecycle.restored_visibility = await page.evaluate(() => document.visibilityState);
      assert.equal(evidence.visibility_lifecycle.restored_visibility, originalVisibility);
    }
    await expect(element(page, 'connection-status')).toContainText(/已连接|online/i);
    passed('Simulated H5 hide stops polling for 3.2s; show resumes an actual V1 snapshot request', evidence.visibility_lifecycle);

    const originalSnapshotResponse = await fetch(base + '/api/v1/dashboard/snapshot');
    assert.equal(originalSnapshotResponse.status, 200);
    const originalSnapshot = await originalSnapshotResponse.json();
    let category;
    await page.route('**/api/v1/dashboard/snapshot', route => route.fulfill({ status: 200,
      contentType: 'application/json', body: JSON.stringify({ ...originalSnapshot, data_available: true,
        emotion: { category, confidence: 0.7, valence: 0.2, arousal: 0.3, attention_level: 0.5,
          vision_emotion: category, speech_emotion: category, environment_signal: 'unknown',
          emotional_cause: 'API CONTRACT ROBUSTNESS FIXTURE — not actual inference', timestamp: new Date().toISOString() },
      }),
    }));
    try {
      for (category of ['__proto__', 'constructor', 'toString']) {
        await expect(element(page, 'emotion-label')).toHaveText(category, { timeout: 10000 });
        assert.deepEqual(fatal, [], `${category} must remain plain safe text without a browser exception`);
      }
    } finally {
      await page.unroute('**/api/v1/dashboard/snapshot');
    }
    await expect(element(page, 'emotion-label')).toContainText(/暂无|等待|尚无|未观测/, { timeout: 10000 });
    await expect(element(page, 'confidence-value')).toHaveText(/^(置信度\s*)?(--|—|暂无数据|未观测)$/);
    passed('Schema-valid unknown categories __proto__/constructor/toString render safely; actual null live state restores', {
      stimulus: 'Snapshot contract interception based on actual V1 shape; not actual inference',
    });
    await expect(page.getByRole('button', { name: /开始陪伴/ })).toHaveCount(1);
    await element(page, 'start-session').focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/session/);
    await expect(element(page, 'camera-status')).toContainText(/OFF|关闭|未开启/i);
    assert.equal(mediaRequests, 0);
    passed('Actual Start Session primary button exposes button role and activates with Enter without media capture');

    for (const name of ['session', 'insights', 'reports', 'settings', 'home']) {
      await navigate(page, name);
      if (name === 'session') {
        await expect(element(page, 'camera-status')).toContainText(/OFF|关闭|未开启/i);
        await expect(element(page, 'microphone-status')).toContainText(/OFF|关闭|未开启/i);
      }
    }
    assert.equal(await page.evaluate(() => window.__scMediaRequests), 0);
    assert.equal(mediaRequests, 0);
    passed('Five actual H5 pages navigate; camera and microphone stay OFF on Session');

    await checkLayouts(page);

    await page.setViewportSize({ width: 1440, height: 900 });
    let wire = await historyResponse(page, () => navigate(page, 'insights'), 7);
    await expect(element(page, 'history-summary')).toContainText('65');
    const limit = wire.limit;
    assert.ok(limit > 0 && limit < 65, 'History must paginate the fixture');
    await historyResponse(page, () => element(page, 'history-next').click(), 7, limit);
    await historyResponse(page, () => element(page, 'history-prev').click(), 7, 0);
    for (const days of [1, 30, 7]) {
      wire = await historyResponse(page, () => element(page, 'range-' + days).click(), days);
      assert.equal(wire.records.length, limit);
      await expect(element(page, 'history-summary')).toContainText('65');
    }
    await screenshot(page, 'insights-real', true);
    await navigate(page, 'reports');
    const realReport = await reportDownload(page, 'parent-real.md', true);
    assert.ok(realReport.length > 100 && !realReport.includes('DEMO DATA'));
    const actualMarkdown = await fetch(`http://127.0.0.1:${backendPort}/api/v1/reports/parent.md?days=7`);
    assert.equal(actualMarkdown.status, 200);
    assert.equal(realReport.trim(), (await actualMarkdown.text()).trim(), 'Downloaded report must match the actual V1 backend Markdown');
    passed('REAL history is actual 65-record SQLite with 1/7/30-day requests, pagination and real Markdown download', { page_limit: limit });

    await navigate(page, 'settings');
    await element(page, 'mode-demo').click();
    await expect(element(page, 'demo-badge')).toBeVisible();
    await pause(300);
    const demoStart = evidence.api_requests.length;
    for (const name of ['home', 'session', 'insights', 'reports', 'settings']) {
      await navigate(page, name);
      await expect(element(page, 'demo-badge')).toBeVisible();
      if (name === 'reports') assert.match(await reportDownload(page, 'parent-demo.md'), /DEMO DATA|合成演示数据/);
    }
    await pause(2200);
    assert.equal(evidence.api_requests.length, demoStart, 'Explicit DEMO must make zero API requests');
    await screenshot(page, 'settings-demo');
    passed('Explicit DEMO remains labelled on every page, downloads labelled synthetic report and makes zero API requests');

    await navigate(page, 'home');
    const orb = element(page, 'emotion-orb');
    assert.equal(await orb.evaluate(node => node.getAnimations({ subtree: true }).length), 0, 'OS reduced-motion must disable Orb animation');
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    assert.ok(await orb.evaluate(node => node.getAnimations({ subtree: true }).length) > 0, 'The DEMO Orb must exercise the enabled-motion path before OFF is tested');
    await navigate(page, 'settings');
    await expect(page.getByRole('switch', { name: /Emotion Orb/ })).toHaveCount(1);
    await expect(element(page, 'motion-toggle')).toHaveAttribute('aria-checked', 'true');
    await element(page, 'motion-toggle').click();
    await expect(element(page, 'motion-toggle')).toHaveAttribute('aria-checked', 'false');
    await navigate(page, 'home');
    assert.equal(await element(page, 'emotion-orb').evaluate(node => node.getAnimations({ subtree: true }).length), 0, 'Product animation OFF must disable Orb animation');
    await page.keyboard.press('Tab');
    await element(page, 'nav-session').focus();
    const focus = await element(page, 'nav-session').evaluate(node => {
      const style = getComputedStyle(node);
      const box = node.getBoundingClientRect();
      return { width: box.width, height: box.height, label: node.getAttribute('aria-label') || node.textContent,
        outline: style.outlineStyle, outline_width: Number.parseFloat(style.outlineWidth), focused: node.matches(':focus-visible') };
    });
    assert.ok(focus.label.trim().length > 0);
    assert.ok(focus.focused && focus.outline !== 'none' && focus.outline_width >= 1, 'Keyboard navigation must show an actual visible focus outline');
    evidence.keyboard_focus = focus;
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/session/);
    await expect(element(page, 'camera-status')).toContainText(/OFF|关闭|未开启/i);
    for (const id of ['nav-home', 'nav-session', 'nav-insights', 'nav-reports', 'nav-settings']) {
      const box = await element(page, id).boundingBox();
      assert.ok(box.width >= 43.5 && box.height >= 43.5, `${id} touch target below 44px`);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await navigate(page, 'insights');
    for (const id of ['nav-home', 'nav-session', 'nav-insights', 'nav-reports', 'nav-settings', 'range-1', 'range-7', 'range-30']) {
      const box = await element(page, id).boundingBox();
      assert.ok(box.width >= 43.5 && box.height >= 43.5, `${id} mobile touch target below 44px`);
    }
    passed('Actual main/navigation/heading roles render; reduced-motion/product OFF disable Orb; keyboard works; desktop/mobile nav and mobile ranges have 44px targets');

    await navigate(page, 'settings');
    await element(page, 'mode-real').click();
    await expect(element(page, 'connection-status')).toContainText(/已连接|online/i, { timeout: 20000 });
    await expect(element(page, 'demo-badge')).toBeHidden();
    await navigate(page, 'home');
    await expect(element(page, 'connection-status')).toContainText(/已连接|online/i, { timeout: 20000 });
    await page.route('**/api/v1/dashboard/snapshot', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{"mode":"real"}' }));
    await expect(element(page, 'connection-status')).toContainText(/ERROR|格式|错误/i, { timeout: 15000 });
    await expect(element(page, 'demo-badge')).toBeHidden();
    await screenshot(page, 'malformed-error');
    await page.unroute('**/api/v1/dashboard/snapshot');
    await element(page, 'retry-connection').click();
    await expect(element(page, 'connection-status')).toContainText(/已连接|online/i);
    passed('Malformed actual snapshot contract shows ERROR; no automatic DEMO and explicit retry recovers REAL');

    await stop(backend);
    backend = null;
    await expect(element(page, 'connection-status')).toContainText(/OFFLINE|离线|未连接|断开/i, { timeout: 20000 });
    await expect(element(page, 'demo-badge')).toBeHidden();
    await screenshot(page, 'offline');
    backend = await start(PYTHON, ['scripts/acceptance_server.py', '--port', String(backendPort), '--db', database], backendPort, '/healthz', 'backend-restarted');
    await element(page, 'retry-connection').click();
    await expect(element(page, 'connection-status')).toContainText(/已连接|online/i, { timeout: 20000 });
    await historyResponse(page, () => navigate(page, 'insights'), 7);
    await expect(element(page, 'history-summary')).toContainText('65');
    passed('Backend graceful stop is verified by TCP refusal; OFFLINE recovers REAL and persisted 65-record history after restart');

    expectedRenderFailure = true;
    try {
      await page.evaluate(() => {
        window.__scOriginalDateFormatter = Date.prototype.toLocaleDateString;
        Date.prototype.toLocaleDateString = () => { throw new Error('private-render-marker'); };
      });
      await element(page, 'nav-home').click();
      await expect(element(page, 'client-error-boundary')).toBeVisible();
      await expect(element(page, 'client-error-boundary')).not.toContainText('private-render-marker');
      await pause(500);
      const stoppedRequests = evidence.api_requests.length;
      await pause(3200);
      assert.equal(evidence.api_requests.length, stoppedRequests, 'Render fallback must unmount active polling');
      await screenshot(page, 'render-fallback');
    } finally {
      await page.evaluate(() => {
        Date.prototype.toLocaleDateString = window.__scOriginalDateFormatter;
        delete window.__scOriginalDateFormatter;
      });
    }
    const restoredSnapshot = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/dashboard/snapshot' && response.status() === 200);
    await element(page, 'client-error-retry').focus();
    await page.keyboard.press('Enter');
    const recovered = await (await restoredSnapshot).json();
    assert.equal(recovered.mode, 'real');
    await expect(element(page, 'connection-status')).toContainText(/已连接|online/i);
    await expect(element(page, 'client-error-boundary')).toHaveCount(0);
    expectedRenderFailure = false;
    evidence.expected_render_fault_count = expectedRenderExceptions.length;
    passed('Deliberate render fault shows generic recoverable fallback, stops polling for 3.2s and keyboard retry restores actual REAL snapshot', {
      stimulus: 'Injected Date formatter exception; not a normal runtime failure',
      expected_renderer_exception_count: expectedRenderExceptions.length,
    });

    assert.equal(await page.evaluate(() => window.__scMediaRequests), 0);
    assert.equal(mediaRequests, 0);
    assert.deepEqual(fatal, []);
    evidence.fatal_errors = fatal;
    evidence.console_errors = consoleErrors;
    evidence.media_permission_requests = mediaRequests;
    passed('Zero uncaught browser exceptions and zero page-load camera/microphone permission requests');
    }
    checksComplete = true;
  } catch (error) {
    failure = error;
    evidence.status = 'failed';
    evidence.failure = error.stack || error.message;
  } finally {
    const cleanupErrors = [];
    if (browser) { try { await browser.close(); } catch (error) { cleanupErrors.push(error); } }
    for (const child of [...children]) { try { await stop(child); } catch (error) { cleanupErrors.push(error); } }
    if (cleanupErrors.length) {
      evidence.status = 'failed';
      evidence.cleanup_errors = cleanupErrors.map(error => error.stack || error.message);
      failure ||= new AggregateError(cleanupErrors, 'Owned client acceptance cleanup failed');
    }
    evidence.status = checksComplete && !failure ? 'passed' : 'failed';
    evidence.finished_at = new Date().toISOString();
    save();
  }
  if (failure) throw failure;
}

(process.argv[2] === '--preview-worker' ? previewWorker() : acceptance())
  .catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
