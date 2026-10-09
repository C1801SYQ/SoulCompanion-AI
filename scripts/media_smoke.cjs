/** Phase03 native Chromium capture with virtual devices. No physical user hardware is opened. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { randomUUID } = require('node:crypto');
const { chromium, expect } = require('@playwright/test');

const ROOT = path.resolve(__dirname, '..');
const OUTPUT = path.join(ROOT, '.test-artifacts', 'v2-media-acceptance');
const PYTHON = process.env.SOULCOMPANION_PYTHON || 'python';
const DEMO_ONLY = process.argv.includes('--demo-only');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const element = (page, id) => page.locator(`#${id}:visible`).first();
const exited = child => child.exitCode !== null || child.signalCode !== null;
const apiQueryRules = new Map([
  ['/api/v1/dashboard/snapshot', []], ['/api/v1/system/status', []],
  ['/api/v1/system/settings', []], ['/api/v1/system/readiness', []],
  ['/api/v1/emotions/history', ['days', 'limit', 'offset']],
  ['/api/v1/emotions/analytics', ['days']], ['/api/v1/reports/parent', ['days']],
  ['/api/v1/reports/parent.md', ['days']],
]);

function knownStaticPaths(directory) {
  const paths = new Set();
  function visit(folder) {
    for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
      const filename = path.join(folder, entry.name);
      if (entry.isDirectory()) visit(filename);
      else if (entry.isFile()) paths.add('/' + path.relative(directory, filename).split(path.sep).join('/'));
    }
  }
  visit(directory);
  return paths;
}

function allowedRequest(request, origin, staticPaths) {
  const url = new URL(request.url());
  if (url.origin !== origin || !['GET', 'HEAD'].includes(request.method())) return false;
  const parameters = apiQueryRules.get(url.pathname);
  if (parameters) {
    if (request.method() !== 'GET') return false;
    const seen = new Set();
    for (const [name, value] of url.searchParams) {
      if (!parameters.includes(name) || seen.has(name)) return false;
      seen.add(name);
      if (name === 'days' && !['1', '7', '30'].includes(value)) return false;
      if (name !== 'days' && (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)))) return false;
      if (name === 'limit' && (Number(value) < 1 || Number(value) > 100)) return false;
      if (name === 'offset' && Number(value) > 1_000_000) return false;
    }
    return true;
  }
  if (url.search || url.hash) return false;
  let pathname;
  try { pathname = decodeURIComponent(url.pathname); } catch { return false; }
  return staticPaths.has(pathname) || ['/', '/community', '/knowledge', '/growth', '/profile', '/home', '/session', '/insights', '/reports', '/settings'].includes(pathname);
}

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
      socket.once('error', error => { socket.destroy(); error.code === 'ECONNREFUSED' ? resolve(true) : reject(error); });
      socket.setTimeout(3000, () => { socket.destroy(); resolve(false); });
    });
    if (closed) return;
    await pause(100);
  }
  throw new Error(`Owned media fixture TCP port ${port} did not give ECONNREFUSED`);
}

/** Observe native APIs inside the isolated browser, keeping only aggregate metadata in evidence. */
function installProbe() {
  const probe = window.__scMediaProbe = {
    mode: 'native', requests: [], streams: [], contexts: [], videos: [], worklets: [], pending: [],
    images: [], pcm: [], storageWrites: 0, frameworkProbeWrites: 0, forbiddenStorageWrites: 0, captureStorageWrites: 0,
    storageKeys: [], storageEvents: [], probeErrors: [], indexedDB: 0, cache: 0,
  };
  const gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async constraints => {
    const mode = probe.mode;
    probe.requests.push({ camera: Boolean(constraints.video), microphone: Boolean(constraints.audio), mode,
      facing: constraints.video?.facingMode?.ideal || null, device_selected: Boolean(constraints.video?.deviceId) });
    // These errors are explicitly injected scenarios, separate from native success evidence.
    if (mode === 'denied') throw new DOMException('Injected permission refusal', 'NotAllowedError');
    if (mode === 'missing') throw new DOMException('Injected missing device', 'NotFoundError');
    const stream = await gum(constraints);
    probe.streams.push(stream);
    if (mode === 'delayed') await new Promise(resolve => probe.pending.push(resolve));
    return stream;
  };
  const NativeContext = window.AudioContext;
  window.AudioContext = class extends NativeContext {
    constructor(...args) { super(...args); probe.contexts.push(this); }
  };
  const NativeWorklet = window.AudioWorkletNode;
  window.AudioWorkletNode = class extends NativeWorklet {
    constructor(...args) {
      super(...args); probe.worklets.push(this);
      this.port.addEventListener('message', event => {
        if (event.data?.type !== 'pcm' || !(event.data.samples instanceof ArrayBuffer)) return;
        const samples = new Int16Array(event.data.samples);
        let sumSquares = 0;
        for (const sample of samples) sumSquares += (sample / 32768) ** 2;
        const rms = samples.length ? Math.sqrt(sumSquares / samples.length) : 0;
        probe.pcm.push({ byteLength: samples.byteLength, sampleRate: event.data.sampleRate,
          sampleCount: samples.length, rms, nonzero: rms > 0 });
        if (probe.pcm.length > 100) probe.pcm.shift();
      });
    }
  };
  const create = document.createElement.bind(document);
  document.createElement = (...args) => {
    const node = create(...args);
    if (String(args[0]).toLowerCase() === 'video') probe.videos.push(node);
    return node;
  };
  const toBlob = HTMLCanvasElement.prototype.toBlob;
  HTMLCanvasElement.prototype.toBlob = function(callback, ...args) {
    const width = this.width, height = this.height;
    return toBlob.call(this, blob => {
      if (blob) {
        void blob.slice(0, 12).arrayBuffer().then(buffer => {
          const bytes = new Uint8Array(buffer);
          const format = bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255 ? 'image/jpeg'
            : String.fromCharCode(...bytes.slice(0, 4)) === 'RIFF' && String.fromCharCode(...bytes.slice(8, 12)) === 'WEBP' ? 'image/webp' : 'unknown';
          probe.images.push({ width, height, byteLength: blob.size, mime: blob.type, format });
          if (probe.images.length > 100) probe.images.shift();
        }).catch(() => { probe.probeErrors.push('Canvas signature metadata could not be read'); });
      }
      callback(blob);
    }, ...args);
  };
  const setItem = Storage.prototype.setItem;
  Storage.prototype.setItem = function(key, value) {
    // jsonp-retry tests localStorage once at module initialization and immediately removes this fixed key.
    // Permit that exact known dependency probe only; every product/session write remains forbidden.
    const frameworkProbe = this === window.localStorage && key === '__store__' && value === JSON.stringify('__store__')
      && probe.requests.length === 0 && probe.frameworkProbeWrites === 0;
    probe.storageWrites += 1;
    if (frameworkProbe) probe.frameworkProbeWrites += 1;
    else probe.forbiddenStorageWrites += 1;
    if (probe.requests.length > 0) probe.captureStorageWrites += 1;
    probe.storageKeys.push(String(key));
    probe.storageEvents.push({ key: String(key).slice(0, 80), valueLength: String(value).length,
      frameworkInitializationProbe: frameworkProbe, permissionRequests: probe.requests.length,
      stack: new Error('Storage write observation').stack?.split('\n').slice(1, 6).join('\n') });
    return setItem.call(this, key, value);
  };
  const openDatabase = indexedDB.open.bind(indexedDB);
  indexedDB.open = (...args) => { probe.indexedDB += 1; return openDatabase(...args); };
  if (window.caches) {
    const openCache = caches.open.bind(caches);
    caches.open = (...args) => { probe.cache += 1; return openCache(...args); };
  }
}

async function probeState(page) {
  return page.evaluate(() => {
    const probe = window.__scMediaProbe;
    const count = id => Number(document.getElementById(id)?.textContent.match(/\d+/)?.[0] || 0);
    return {
      requests: probe.requests, tracks: probe.streams.flatMap(stream => stream.getTracks().map(track => ({ kind: track.kind, state: track.readyState }))),
      contexts: probe.contexts.map(context => ({ state: context.state, sampleRate: context.sampleRate })),
      attachedVideos: probe.videos.filter(video => video.srcObject !== null).length,
      workletInstances: probe.worklets.length, images: probe.images, pcm: probe.pcm,
      frames: count('media-frame-count'), audio: count('media-audio-count'),
      storageWrites: probe.storageWrites, storageKeys: probe.storageKeys, storageEvents: probe.storageEvents, probeErrors: probe.probeErrors,
      frameworkProbeWrites: probe.frameworkProbeWrites, frameworkProbeRemoved: localStorage.getItem('__store__') === null,
      forbiddenStorageWrites: probe.forbiddenStorageWrites, captureStorageWrites: probe.captureStorageWrites,
      indexedDB: probe.indexedDB, cache: probe.cache,
      visibility: { hidden: document.hidden, state: document.visibilityState, online: navigator.onLine },
      sessionStatus: document.getElementById('session-status')?.textContent || '',
      mediaProblem: document.getElementById('media-problem')?.textContent || '',
    };
  });
}

async function acceptance() {
  fs.mkdirSync(OUTPUT, { recursive: true });
  const run = fs.mkdtempSync(path.join(OUTPUT, 'run-'));
  const evidence = { status: 'running', started_at: new Date().toISOString(), run_directory: run,
    build_mode: DEMO_ONLY ? 'demo-only' : 'real-capable', checks: [], screenshots: [], responsive: [], cleanup: [],
    fixture: 'Native Chromium getUserMedia/canvas/AudioWorklet with Chromium virtual camera and microphone',
    limitations: ['Physical Windows camera, Android browser, iPhone browser and WeChat hardware NOT TESTED',
      'Permission refusal, missing devices and delayed grant are injected API scenarios; successful streams use native Chromium virtual devices',
      'Storage checks observe browser writes during tested sessions, alongside unit tests; this is not an exhaustive platform forensic audit'],
  };
  const fatal = [], mutations = [], apiRequests = [], downloads = [], networkRequests = [], blockedRequests = [], webSockets = [];
  evidence.diagnostics = { fatal, mutations, api_requests: apiRequests, downloads,
    network_requests: networkRequests, blocked_requests: blockedRequests, websocket_attempts: webSockets };
  const save = () => {
    const json = JSON.stringify(evidence, null, 2) + '\n';
    fs.writeFileSync(path.join(run, 'results.json'), json);
    fs.writeFileSync(path.join(OUTPUT, 'results.json'), json);
  };
  save();
  const children = new Set();
  let browser, page, failure, complete = false;
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
    Object.assign(child, { stopFile, fixturePort: port, fixtureName: name }); children.add(child);
    let spawnError; child.on('error', error => { spawnError = error; });
    for (let attempt = 0; attempt < 100; attempt++) {
      if (spawnError) throw spawnError;
      if (exited(child)) throw new Error(`${name} exited before ready; see ${name}.log`);
      try { if ((await fetch(`http://127.0.0.1:${port}${readyPath}`, { signal: AbortSignal.timeout(700) })).ok) return child; } catch { /* Owned fixture is still starting. */ }
      await pause(100);
    }
    throw new Error(`${name} did not become ready`);
  }
  function passed(name, details = {}) {
    evidence.checks.push({ name, status: 'passed', ...details }); save(); process.stdout.write(`PASS ${name}\n`);
  }
  async function screenshot(page, name) {
    const filename = path.join(run, `${name}.png`);
    await page.screenshot({ path: filename, fullPage: true, animations: 'disabled' }); evidence.screenshots.push(filename);
  }
  async function active(page) {
    await element(page, 'session-start').click();
    await expect(element(page, 'camera-status')).toContainText('Camera ON', { timeout: 15000 });
    await expect(element(page, 'microphone-status')).toContainText('Mic ON', { timeout: 15000 });
    await expect(element(page, 'session-stop')).toBeEnabled();
    await expect.poll(async () => {
      const state = await probeState(page);
      return state.frames > 0 && state.audio > 0 && state.images.length > 0 && state.pcm.length > 0;
    }, { timeout: 15000 }).toBe(true);
    await expect(element(page, 'session-emotion-status')).toContainText('本次尚无情绪推理结果');
  }
  async function released(page) {
    await expect.poll(async () => {
      const state = await probeState(page);
      return state.tracks.every(track => track.state === 'ended') && state.contexts.every(context => context.state === 'closed') && state.attachedVideos === 0;
    }, { timeout: 15000 }).toBe(true);
    await expect(element(page, 'session-start')).toBeEnabled();
    const before = await probeState(page);
    await pause(1800);
    const after = await probeState(page);
    assert.equal(after.frames, before.frames, 'Stopped image metadata must not increase');
    assert.equal(after.audio, before.audio, 'Stopped audio metadata must not increase');
    assert.equal(after.requests.length, before.requests.length, 'Recovery must not automatically acquire devices');
    return after;
  }
  try {
    assert.ok(fs.existsSync(path.join(ROOT, 'apps/client/dist/index.html')), 'Build H5 before media acceptance');
    const backendPort = await freePort(), previewPort = await freePort();
    const backend = await start(PYTHON, ['scripts/acceptance_server.py', '--port', String(backendPort), '--db', path.join(run, 'synthetic.sqlite'), '--seed'], backendPort, '/healthz', 'backend');
    await start(process.execPath, [path.join(ROOT, 'scripts/client_smoke.cjs'), '--preview-worker', '--port', String(previewPort), '--upstream-port', String(backendPort)], previewPort, '/', 'preview');
    browser = await chromium.launch({ headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, permissions: ['camera', 'microphone'], serviceWorkers: 'block' });
    await context.addInitScript(installProbe);
    page = await context.newPage();
    const origin = `http://127.0.0.1:${previewPort}`;
    const staticPaths = knownStaticPaths(path.join(ROOT, 'apps/client/dist'));
    await context.route('**/*', async route => {
      if (allowedRequest(route.request(), origin, staticPaths)) await route.continue();
      else {
        blockedRequests.push({ url: route.request().url(), method: route.request().method() });
        await route.abort('blockedbyclient');
      }
    });
    await page.routeWebSocket('**', socket => {
      webSockets.push({ url: socket.url(), blocked: true });
      void socket.close({ code: 1008, reason: 'Media acceptance forbids socket traffic' })
        .catch(() => fatal.push('Forbidden WebSocket could not be closed'));
    });
    page.on('websocket', socket => webSockets.push({ url: socket.url(), observed: true }));
    page.on('pageerror', error => fatal.push(error.message));
    page.on('download', download => downloads.push(download.suggestedFilename()));
    context.on('request', request => {
      networkRequests.push({ url: request.url(), method: request.method(), type: request.resourceType(), allowed: allowedRequest(request, origin, staticPaths) });
      if (!['GET', 'HEAD'].includes(request.method())) mutations.push({ method: request.method(), url: request.url() });
      if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.url());
    });
    await page.goto(`http://127.0.0.1:${previewPort}/#/home`);
    if (DEMO_ONLY) await expect(element(page, 'demo-badge')).toBeVisible();
    else {
      await expect(element(page, 'connection-status')).toContainText('已连接', { timeout: 15000 });
      await element(page, 'nav-settings').click();
      await element(page, 'mode-demo').click();
      await expect(element(page, 'demo-badge')).toBeVisible();
    }
    await element(page, 'nav-session').click();
    await expect(element(page, 'camera-status')).toContainText('Camera OFF');
    await expect(element(page, 'microphone-status')).toContainText('Mic OFF');
    await expect(element(page, 'microphone-input-level')).toContainText('尚未获得读数');
    await pause(800);
    const initialized = await probeState(page);
    assert.equal(initialized.requests.length, 0);
    assert.equal(initialized.forbiddenStorageWrites, 0, 'Unknown initialization Storage writes are forbidden');
    assert.ok(initialized.frameworkProbeWrites <= 1 && initialized.frameworkProbeRemoved,
      'The fixed jsonp-retry initialization probe must be removed before any device permission request');
    await element(page, 'camera-list-refresh').click();
    assert.equal((await probeState(page)).requests.length, 0, 'Device enumeration must not request permissions');
    passed('Page load, navigation and explicit camera listing acquire zero devices; DEMO local Start is available');

    const apiBeforeCapture = apiRequests.length;
    await active(page);
    const video = await element(page, 'media-preview-video').evaluate(node => ({ width: node.videoWidth, height: node.videoHeight, ready: node.readyState,
      autoplay: node.autoplay, muted: node.muted, playsInline: node.playsInline }));
    assert.ok(video.width > 0 && video.height > 0 && video.ready >= 2);
    assert.ok(video.autoplay && video.muted && video.playsInline);
    let state = await probeState(page);
    assert.equal(state.requests.length, 2);
    assert.deepEqual(state.tracks.map(track => track.kind).sort(), ['audio', 'video']);
    assert.ok(state.tracks.every(track => track.state === 'live'));
    assert.ok(state.images.every(image => image.mime === image.format && image.byteLength <= 200 * 1024 && image.width <= 640 && image.height <= 480));
    assert.ok(state.pcm.every(pcm => pcm.byteLength === pcm.sampleRate * 2 && pcm.byteLength + 44 <= 128 * 1024));
    await expect.poll(async () => (await probeState(page)).pcm.some(pcm => Number.isFinite(pcm.rms) && pcm.rms > 0 && pcm.nonzero), { timeout: 15000 }).toBe(true);
    state = await probeState(page);
    const inputPcm = state.pcm.find(pcm => pcm.nonzero && pcm.rms > 0);
    assert.ok(inputPcm, 'Native virtual microphone must produce nonzero measured PCM RMS');
    await expect(element(page, 'microphone-input-level')).toContainText(/\d+%/, { timeout: 10000 });
    const displayedInput = await element(page, 'microphone-input-level').innerText();
    const inputPercent = Number(displayedInput.match(/(\d+)%/)?.[1]);
    assert.ok(Number.isInteger(inputPercent) && inputPercent >= 0 && inputPercent <= 100);
    await screenshot(page, 'native-virtual-devices-active');
    passed('Explicit Start uses native virtual video/audio tracks, visible preview, bounded real image encoding and nonzero AudioWorklet PCM', {
      video, tracks: state.tracks, image: state.images[0], pcm: inputPcm, displayed_input_percent: inputPercent,
      input_note: 'PCM RMS is the actual float measurement; UI rounds an independently sampled level and may honestly show 0%',
    });

    for (const [width, height] of [[375, 812], [390, 844], [430, 932], [768, 900], [1024, 900], [1440, 900]]) {
      await page.setViewportSize({ width, height });
      const layout = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth,
        areas: [...document.querySelectorAll('.sc-main,.sc-preview-card,.sc-local-session-controls,.sc-media-actions')].map(node => ({ className: node.className, width: node.clientWidth, content: node.scrollWidth })) }));
      assert.ok(layout.document <= width + 1);
      layout.areas.forEach(area => assert.ok(area.content <= area.width + 1, `${area.className} overflows at ${width}`));
      for (const id of ['session-start', 'session-stop', 'camera-enabled', 'microphone-enabled', 'camera-facing-user', 'camera-facing-environment']) {
        await expect(element(page, id)).toHaveAttribute('role', id.endsWith('-enabled') ? 'switch' : 'button');
        const box = await element(page, id).boundingBox();
        assert.ok(box && box.width >= 43.5 && box.height >= 43.5, `${id} below 44px at ${width}`);
        if (width < 600 && ['session-start', 'session-stop'].includes(id)) {
          const nav = await element(page, 'nav-community').boundingBox();
          assert.ok(box.y >= 0 && box.y + box.height <= nav.y, `${id} below mobile first screen at ${width}`);
        }
      }
      evidence.responsive.push({ width, height, ...layout });
      if (width < 600 || width === 1440) await screenshot(page, `active-${width}`);
    }
    passed('Active native preview and controls fit all six widths; Start/End fit each mobile first screen and controls expose roles/44px targets');

    await element(page, 'session-stop').focus();
    await page.keyboard.press('Enter');
    state = await released(page);
    await expect(element(page, 'camera-status')).toContainText('Camera OFF');
    await expect(element(page, 'microphone-status')).toContainText('Mic OFF');
    await expect(element(page, 'microphone-input-level')).toContainText('尚未获得读数');
    passed('Keyboard End releases every track, closes AudioContexts, detaches all videos and stops metadata counts', { tracks: state.tracks, contexts: state.contexts });

    await active(page);
    await page.evaluate(() => { document.getElementById('session-start').click(); document.getElementById('session-start').click(); });
    assert.equal((await probeState(page)).requests.length, 4, 'Disabled duplicate Starts must not acquire more streams');
    await element(page, 'session-stop').click();
    await released(page);
    passed('A second explicit Start succeeds; duplicate active Starts acquire no extra streams');

    await active(page);
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, value: true });
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await released(page);
    await page.evaluate(() => { delete document.hidden; delete document.visibilityState; document.dispatchEvent(new Event('visibilitychange')); });
    await released(page);
    passed('Injected browser visibility event stops native capture; returning visible does not restart');

    await active(page);
    await context.setOffline(true);
    await released(page);
    await context.setOffline(false);
    await released(page);
    passed('Browser transport offline stops native capture; online recovery does not restart');

    await active(page);
    await element(page, 'nav-home').click();
    await expect.poll(async () => (await probeState(page)).tracks.every(track => track.state === 'ended')).toBe(true);
    const left = await probeState(page);
    assert.ok(left.contexts.every(context => context.state === 'closed'));
    assert.equal(left.attachedVideos, 0);
    await element(page, 'start-session').click();
    await expect(element(page, 'camera-status')).toContainText('Camera OFF');
    await released(page);
    passed('Navigation away releases native hardware; Home Start only navigates and never automatically opens devices');

    await active(page);
    const beforeCommunity = (await probeState(page)).requests.length;
    await element(page, 'nav-community').click();
    await expect(element(page, 'community-preview-badge')).toBeVisible();
    await expect.poll(async () => (await probeState(page)).tracks.every(track => track.state === 'ended')).toBe(true);
    const onCommunity = await probeState(page);
    assert.ok(onCommunity.contexts.every(context => context.state === 'closed'));
    assert.equal(onCommunity.attachedVideos, 0);
    assert.equal(onCommunity.requests.length, beforeCommunity, 'Community cannot acquire replacement media');
    await element(page, 'nav-growth').click();
    await element(page, 'pc-tool-session').click();
    await released(page);
    await expect(element(page, 'camera-status')).toContainText('Camera OFF');
    passed('Active media → community releases tracks/contexts/preview; returning via Growth does not restart capture');

    for (const mode of ['denied', 'missing']) {
      await page.evaluate(value => { window.__scMediaProbe.mode = value; }, mode);
      const prior = (await probeState(page)).requests.length;
      await element(page, 'session-start').click();
      await expect(element(page, 'media-problem')).toContainText(mode === 'denied' ? '权限' : '没有找到');
      const status = mode === 'denied' ? 'DENIED' : 'UNAVAILABLE';
      await expect.poll(async () => {
        const labels = `${await element(page, 'camera-status').innerText()} ${await element(page, 'microphone-status').innerText()}`;
        return labels.includes(status);
      }).toBe(true);
      await released(page);
      const requests = (await probeState(page)).requests.length;
      assert.ok(requests > prior);
      await pause(1200);
      assert.equal((await probeState(page)).requests.length, requests, 'Failure recovery must not repeatedly prompt');
      await screenshot(page, `injected-${mode}`);
      passed(`Injected ${mode} API error is explicit ${status}, recoverable and never auto-retries`, { stimulus: 'Injected DOMException; not a physical hardware result' });
    }

    await page.evaluate(() => { window.__scMediaProbe.mode = 'delayed'; });
    await element(page, 'session-start').click();
    await expect(element(page, 'camera-status')).toContainText('REQUESTING');
    await expect.poll(() => page.evaluate(() => window.__scMediaProbe.pending.length)).toBe(2);
    await element(page, 'session-stop').click();
    await expect(element(page, 'session-start')).toBeEnabled();
    await page.evaluate(() => { window.__scMediaProbe.pending.splice(0).forEach(resolve => resolve()); window.__scMediaProbe.mode = 'native'; });
    await released(page);
    await expect(element(page, 'camera-status')).not.toContainText('Camera ON');
    await expect(element(page, 'microphone-status')).not.toContainText('Mic ON');
    passed('Injected delayed delivery of actual native grants is canceled by End; late tracks close without preview or samples', { stimulus: 'Delay wrapper around native getUserMedia virtual streams' });

    await active(page);
    await element(page, 'session-stop').click();
    await released(page);
    await expect(element(page, 'camera-device-0')).toBeVisible();
    await element(page, 'camera-device-0').click();
    await active(page);
    const selected = (await probeState(page)).requests.at(-2);
    assert.equal(selected.camera, true); assert.equal(selected.device_selected, true);
    await element(page, 'session-stop').click();
    await released(page);
    passed('Granted camera enumeration and explicit device selection apply only to the next Start');

    await stop(backend);
    await active(page);
    await element(page, 'session-stop').click();
    state = await released(page);
    passed('DEMO local preview still acquires native virtual devices with the emotion API fixture stopped');
    assert.equal(apiRequests.length, apiBeforeCapture, 'DEMO media capture must never request the emotion API');
    if (DEMO_ONLY) assert.equal(apiRequests.length, 0, 'PUBLIC_DEMO_ONLY build must make zero API requests across the entire run');
    assert.deepEqual(mutations, [], 'Local media must never POST/PUT/upload');
    assert.deepEqual(downloads, [], 'Raw media must never download automatically');
    assert.equal(state.forbiddenStorageWrites, 0, 'All Storage writes except the exact removed pre-permission framework probe are forbidden');
    assert.equal(state.captureStorageWrites, 0, 'Every localStorage/sessionStorage write after the first permission request is forbidden');
    assert.equal(state.storageWrites, state.frameworkProbeWrites);
    assert.ok(state.frameworkProbeWrites <= 1 && state.frameworkProbeRemoved);
    assert.deepEqual(state.probeErrors, [], 'Asynchronous metadata observers must not fail silently');
    assert.equal(state.indexedDB, 0); assert.equal(state.cache, 0);
    assert.deepEqual(blockedRequests, [], 'No request may leave the known same-origin static/fixture allowlist');
    assert.ok(networkRequests.every(request => request.allowed), 'All observed HTTP requests must be allowlisted');
    assert.deepEqual(webSockets, [], 'Local media must never create a WebSocket');
    assert.deepEqual(fatal, []);
    evidence.final_resources = { requests: state.requests.length, tracks: state.tracks, contexts: state.contexts, attached_videos: state.attachedVideos };
    evidence.diagnostics.security_counts = { observed_http_requests: networkRequests.length, blocked_http_requests: blockedRequests.length,
      websocket_attempts: webSockets.length, mutations: mutations.length, storage_set_item_writes: state.storageWrites,
      framework_initialization_probe_writes: state.frameworkProbeWrites, framework_initialization_probe_removed: state.frameworkProbeRemoved,
      forbidden_storage_writes: state.forbiddenStorageWrites, capture_storage_writes: state.captureStorageWrites,
      indexed_db_opens: state.indexedDB, cache_opens: state.cache, automatic_downloads: downloads.length,
      api_requests_during_capture: apiRequests.length - apiBeforeCapture };
    passed('No uncaught exceptions, media uploads, unknown GET traffic, WebSockets, downloads, capture Storage writes, IndexedDB or cache opens; exact framework initialization probe is removed', {
      storage_total: state.storageWrites, fixed_pre_permission_framework_probes: state.frameworkProbeWrites,
      framework_probe_removed: state.frameworkProbeRemoved, forbidden_storage_writes: state.forbiddenStorageWrites,
      capture_storage_writes: state.captureStorageWrites,
    });
    complete = true;
  } catch (error) {
    failure = error; evidence.status = 'failed'; evidence.failure = error.stack || error.message;
    if (page && !page.isClosed()) {
      try { evidence.diagnostics.last_probe = await probeState(page); }
      catch (probeError) { evidence.diagnostics.probe_failure = probeError.message; }
    }
  } finally {
    const errors = [];
    if (browser) { try { await browser.close(); } catch (error) { errors.push(error); } }
    for (const child of [...children]) { try { await stop(child); } catch (error) { errors.push(error); } }
    if (errors.length) { evidence.cleanup_errors = errors.map(error => error.stack || error.message); failure ||= new AggregateError(errors, 'Owned media acceptance cleanup failed'); }
    evidence.status = complete && !failure ? 'passed' : 'failed'; evidence.finished_at = new Date().toISOString(); save();
  }
  if (failure) throw failure;
}

acceptance().catch(error => { process.stderr.write((error.stack || error.message) + '\n'); process.exitCode = 1; });
