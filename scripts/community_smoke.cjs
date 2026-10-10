/** PC01 synthetic parent-community acceptance. An owned static server, no backend or cloud writes. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const net = require('node:net');
const { chromium, expect } = require('@playwright/test');

const ROOT = path.resolve(__dirname, '..');
const DIST = path.join(ROOT, 'apps', 'client', 'dist');
const OUTPUT = path.join(ROOT, '.test-artifacts', 'community-acceptance');
const AGES = ['0-2', '3-5', '6-8', '9-12', '13-15', '16-18'];
const TOPICS = ['parent-child', 'emotional-support', 'daily-habits', 'school-transition', 'learning-peers', 'adolescence', 'parent-growth'];
const SCREENS = [{ width: 375, height: 812 }, { width: 390, height: 844 }, { width: 430, height: 932 },
  { width: 600, height: 900 }, { width: 767, height: 1024 },
  { width: 768, height: 1024 }, { width: 1440, height: 900 }];
const MAIN_PAGES = ['community', 'knowledge', 'growth', 'profile'];
const activeFrame = page => page.locator('.taro_page_show.taro_page_stationed:not(.taro_page_shade):visible').last();
const element = (page, id) => activeFrame(page).locator(`[data-testid="${id}"]:visible, [id="${id}"]:visible`).first();
const cards = page => page.locator('.pc-post-card:visible');

/** H5 URLs update before Taro's entering/leaving frames complete. Wait on the actual target, not a timer. */
async function waitForActivePage(page, route) {
  await page.waitForFunction(expected => {
    const frames = [...document.querySelectorAll('.taro_page_show.taro_page_stationed:not(.taro_page_shade)')].filter(node => {
      const style = getComputedStyle(node), box = node.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && Math.abs(box.left) <= 1;
    });
    if (frames.length !== 1) return false;
    const frame = frames[0], destination = frame.id.split('?')[0];
    return [expected, `/pages${expected}/index`, `/pages${expected}`].includes(destination)
      && getComputedStyle(frame).transform === 'none' && Math.abs(frame.clientWidth - innerWidth) <= 1;
  }, '/' + route);
}

function knownStaticPaths(directory) {
  const result = new Set(['/']);
  function visit(folder) {
    for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
      const filename = path.join(folder, entry.name);
      if (entry.isDirectory()) visit(filename);
      else if (entry.isFile()) result.add('/' + path.relative(directory, filename).split(path.sep).join('/'));
    }
  }
  visit(directory);
  return result;
}

/** Public community pages may load only named files from this isolated build. No API, auth or remote exceptions. */
function allowedRequest(urlString, method, origin, staticPaths) {
  let url;
  try { url = new URL(urlString); } catch { return false; }
  if (url.origin !== origin || url.username || url.password || !['GET', 'HEAD'].includes(method) || url.search || url.hash) return false;
  let pathname;
  try { pathname = decodeURIComponent(url.pathname); } catch { return false; }
  if (pathname.startsWith('/api/') || pathname.includes('\\') || pathname.includes('\0')) return false;
  return staticPaths.has(pathname);
}

async function createPreview(directory) {
  const root = fs.realpathSync(directory);
  const staticPaths = knownStaticPaths(root);
  const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff': 'font/woff', '.woff2': 'font/woff2' };
  let origin;
  const server = http.createServer((request, response) => {
    let absolute;
    try { absolute = new URL(request.url, origin); } catch { response.writeHead(400); response.end(); return; }
    if (!allowedRequest(absolute.href, request.method, origin, staticPaths)) {
      response.writeHead(['GET', 'HEAD'].includes(request.method) ? 404 : 405); response.end(); return;
    }
    try {
      const pathname = decodeURIComponent(absolute.pathname);
      const filename = fs.realpathSync(path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname)));
      if (!filename.startsWith(root + path.sep) || !fs.statSync(filename).isFile()) throw new Error('File boundary');
      response.writeHead(200, { 'Content-Type': mime[path.extname(filename)] || 'application/octet-stream',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
      if (request.method === 'HEAD') { response.end(); return; }
      const stream = fs.createReadStream(filename);
      stream.once('error', error => response.destroy(error)); stream.pipe(response);
    } catch { response.writeHead(404); response.end(); }
  });
  server.on('clientError', (_, socket) => socket.destroy());
  server.on('upgrade', (_, socket) => socket.destroy());
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const port = server.address().port;
  origin = `http://127.0.0.1:${port}`;
  return { origin, port, staticPaths, async close() {
    await new Promise((resolve, reject) => { server.close(error => error ? reject(error) : resolve()); server.closeAllConnections(); });
    // Verify ownership cleanup without a fixed sleep or killing any unrelated process.
    await new Promise((resolve, reject) => {
      const socket = net.createConnection({ host: '127.0.0.1', port });
      socket.once('connect', () => { socket.destroy(); reject(new Error('Owned preview port still accepts connections')); });
      socket.once('error', error => { socket.destroy(); error.code === 'ECONNREFUSED' ? resolve() : reject(error); });
      socket.setTimeout(5000, () => { socket.destroy(); reject(new Error('Owned preview cleanup was inconclusive')); });
    });
  } };
}

/** Guard unintended device access; every attempted call is a failing assertion, never a simulated grant. */
function installPublicProbe() {
  const probe = window.__pc01Probe = { media: 0, enumerate: 0, permissions: 0, storage: 0, frameworkProbe: 0, indexedDB: 0, cache: 0 };
  const media = navigator.mediaDevices;
  if (media) {
    media.getUserMedia = async () => { probe.media += 1; throw new Error('PC01 public route attempted device acquisition'); };
    media.enumerateDevices = async () => { probe.enumerate += 1; throw new Error('PC01 public route attempted device enumeration'); };
  }
  if (navigator.permissions) {
    const query = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = descriptor => {
      if (['camera', 'microphone'].includes(descriptor.name)) { probe.permissions += 1; return Promise.reject(new Error('PC01 public route queried media permission')); }
      return query(descriptor);
    };
  }
  const setItem = Storage.prototype.setItem;
  Storage.prototype.setItem = function(key, value) {
    const frameworkProbe = this === window.localStorage && key === '__store__' && value === JSON.stringify('__store__') && probe.frameworkProbe === 0;
    if (frameworkProbe) probe.frameworkProbe += 1;
    else probe.storage += 1;
    return setItem.call(this, key, value);
  };
  const openDatabase = indexedDB.open.bind(indexedDB);
  indexedDB.open = (...args) => { probe.indexedDB += 1; return openDatabase(...args); };
  if (window.caches) {
    const openCache = caches.open.bind(caches);
    caches.open = (...args) => { probe.cache += 1; return openCache(...args); };
  }
}

async function acceptance() {
  assert.ok(fs.existsSync(path.join(DIST, 'index.html')), 'Build H5 before PC01 acceptance');
  fs.mkdirSync(OUTPUT, { recursive: true });
  const run = fs.mkdtempSync(path.join(OUTPUT, 'run-'));
  const evidence = { status: 'running', started_at: new Date().toISOString(), build_mode: process.argv.includes('--demo-only') ? 'demo-only' : 'real-capable',
    fixture: 'Synthetic community UI with owned loopback static server; no API fixture or cloud resources',
    checks: [], screenshots: [], responsive: [], privacy: {}, cleanup: [], limitations: [
      'WeChat physical devices and platform login are NOT TESTED; this runner uses Chromium H5 only',
      'Real community publication/moderation are NOT IMPLEMENTED; no production data or cloud API is called',
      'Media lifecycle and authenticated owner isolation also require the separate existing regression suites',
      'DOM/keyboard/motion checks are not a full screen-reader or WCAG conformance audit',
    ] };
  const save = () => { const json = JSON.stringify(evidence, null, 2) + '\n'; fs.writeFileSync(path.join(run, 'results.json'), json); fs.writeFileSync(path.join(OUTPUT, 'results.json'), json); };
  const passed = (name, detail) => { evidence.checks.push({ name, status: 'pass', ...(detail ? { detail } : {}) }); console.log('PASS ' + name); save(); };
  let preview, browser, publicContext, failure, inspectedPage;
  const violations = [], pageErrors = [], probes = [];
  save();
  try {
    preview = await createPreview(DIST);
    assert.equal((await fetch(preview.origin + '/api/v2/posts')).status, 404);
    assert.equal((await fetch(preview.origin + '/', { method: 'POST' })).status, 405);
    passed('Owned static fixture rejects API and writes');
    browser = await chromium.launch({ headless: true });
    publicContext = await browser.newContext({ viewport: SCREENS[1], reducedMotion: 'reduce', serviceWorkers: 'block', acceptDownloads: false });
    await publicContext.addInitScript(installPublicProbe);
    await publicContext.route('**/*', async route => {
      const request = route.request();
      if (allowedRequest(request.url(), request.method(), preview.origin, preview.staticPaths)) { await route.continue(); return; }
      // Record only classifications, never payloads, cookies, authentication headers or private identifiers.
      const url = new URL(request.url());
      violations.push({ method: request.method(), kind: url.origin !== preview.origin ? 'remote' : url.pathname.startsWith('/api/') ? 'api' : 'unknown-static' });
      await route.abort('blockedbyclient');
    });
    await publicContext.routeWebSocket('**', socket => { violations.push({ kind: 'websocket' }); socket.close(); });
    const page = await publicContext.newPage();
    inspectedPage = page;
    page.on('pageerror', () => { pageErrors.push('uncaught-public-page-error'); });
    page.on('download', () => { violations.push({ kind: 'download' }); });
    const screenshot = async name => { const filename = path.join(run, name + '.png'); await page.screenshot({ path: filename, fullPage: true, animations: 'disabled' }); evidence.screenshots.push(filename); };
    // Taro H5 scrolls its active page container; window.scrollY alone stays zero even far below the first screen.
    const activeScroll = () => page.getByRole('main').evaluate(node => Math.max(window.scrollY, node.closest('.taro_page')?.scrollTop || 0));
    const assertNoOverflow = async width => {
      await expect.poll(() => page.getByRole('main').evaluate(node => {
        const hosts = [node, node.closest('.taro_page'), node.closest('.sc-shell')].filter(Boolean);
        return Math.max(document.documentElement.scrollWidth - window.innerWidth, ...hosts.map(host => host.scrollWidth - host.clientWidth));
      })).toBeLessThanOrEqual(1);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1 && innerWidth === window.visualViewport.width && innerWidth > 0));
      assert.equal(await page.evaluate(() => innerWidth), width);
    };
    const navigate = async name => {
      await element(page, 'nav-' + name).click();
      await expect(page).toHaveURL(new RegExp(`#/(?:pages/)?${name}(?:/index)?(?:[/?]|$)`));
      await waitForActivePage(page, name);
      await expect(element(page, 'nav-' + name)).toHaveAttribute('aria-current', 'page');
      await expect(element(page, 'community-preview-badge')).toContainText(/产品预览|示例/);
    };
    const publicProbe = async () => {
      const state = await page.evaluate(() => ({ ...window.__pc01Probe, frameworkProbeRemoved: localStorage.getItem('__store__') === null,
        storedKeys: Object.keys(localStorage).length + Object.keys(sessionStorage).length }));
      probes.push(state);
      for (const name of ['media', 'enumerate', 'permissions', 'storage', 'indexedDB', 'cache', 'storedKeys']) assert.equal(state[name], 0, `Public community ${name} must stay zero`);
      assert.equal(state.frameworkProbeRemoved, true, 'The sole permitted dependency storage probe must be removed');
      assert.equal(violations.length, 0, 'Public pages must not attempt private reads, cloud writes, remote requests, unknown files or WebSockets');
      assert.equal(pageErrors.length, 0, 'Public pages must not throw uncaught exceptions');
    };

    await page.goto(preview.origin + '/', { waitUntil: 'networkidle' });
    await waitForActivePage(page, 'community');
    await expect(element(page, 'nav-community')).toHaveAttribute('aria-current', 'page');
    await expect(page).toHaveTitle(/予怀/);
    await expect(element(page, 'community-preview-badge')).toContainText(/产品预览|示例/);
    await expect(cards(page).first()).toBeVisible();
    passed('Default entry is branded parent community, without a login or child-profile gate');

    const allPosts = await cards(page).evaluateAll(nodes => nodes.map(node => ({
      id: node.getAttribute('data-post-id'), age: node.getAttribute('data-age-band'), topic: node.getAttribute('data-topic'), published: node.getAttribute('data-published-at'),
    })));
    assert.ok(allPosts.length >= 7, 'Synthetic fixtures must cover every community topic');
    assert.equal(new Set(allPosts.map(post => post.id)).size, allPosts.length, 'Unique fixture IDs');
    for (const post of allPosts) {
      assert.match(post.id, /^example-\w+$/); assert.ok(AGES.includes(post.age)); assert.ok(TOPICS.includes(post.topic));
      assert.ok(Number.isFinite(Date.parse(post.published)), 'Fixture timestamps must be explicit and parseable');
    }
    assert.deepEqual(allPosts.map(post => Date.parse(post.published)), allPosts.map(post => Date.parse(post.published)).sort((a, b) => b - a));
    const assertFiltered = async expected => {
      await expect(cards(page)).toHaveCount(expected.length);
      assert.deepEqual(await cards(page).evaluateAll(nodes => nodes.map(node => node.getAttribute('data-post-id'))), expected.map(post => post.id));
      await expect(element(page, 'pc-filter-count')).toContainText(new RegExp(`(^|\\D)${expected.length}(\\D|$)`));
      for (let index = 0; index < expected.length; index++) {
        await expect(cards(page).nth(index).locator('.pc-example-label, [data-testid="pc-example-label"], [id="pc-example-label"]').first()).toContainText('示例内容');
      }
      if (expected.length === 0) await expect(element(page, 'pc-community-empty')).toBeVisible();
      else await expect(element(page, 'pc-community-empty')).toHaveCount(0);
    };
    await assertFiltered(allPosts);
    for (const age of AGES) {
      const expected = allPosts.filter(post => post.age === age); assert.ok(expected.length > 0, 'Every age band needs fixture coverage');
      await element(page, 'pc-age-' + age).click(); await expect(element(page, 'pc-age-' + age)).toHaveAttribute('aria-pressed', 'true'); await assertFiltered(expected);
    }
    await element(page, 'pc-age-all').click();
    for (const topic of TOPICS) {
      const expected = allPosts.filter(post => post.topic === topic); assert.ok(expected.length > 0, 'Every topic needs fixture coverage');
      await element(page, 'pc-topic-' + topic).click(); await expect(element(page, 'pc-topic-' + topic)).toHaveAttribute('aria-pressed', 'true'); await assertFiltered(expected);
    }
    for (const age of AGES) {
      await element(page, 'pc-age-' + age).click();
      for (const topic of TOPICS) { await element(page, 'pc-topic-' + topic).click(); await assertFiltered(allPosts.filter(post => post.age === age && post.topic === topic)); }
    }
    assert.ok(AGES.some(age => TOPICS.some(topic => !allPosts.some(post => post.age === age && post.topic === topic))), 'Fixture matrix needs an actual empty combination');
    passed('Six ages, seven topics, all 42 AND combinations, empty states and newest-first example list');

    await element(page, 'pc-age-6-8').click(); await element(page, 'pc-topic-parent-child').click();
    const chosen = allPosts.filter(post => post.age === '6-8' && post.topic === 'parent-child'); assert.ok(chosen.length > 0);
    await assertFiltered(chosen);
    await element(page, 'pc-open-' + chosen[0].id).scrollIntoViewIfNeeded();
    const scrollBefore = await activeScroll();
    await element(page, 'pc-open-' + chosen[0].id).click();
    await expect(page).toHaveURL(/community\/detail\?id=example-/);
    await waitForActivePage(page, 'community/detail');
    await expect(element(page, 'pc-detail-back')).toBeVisible();
    await expect(page.getByRole('heading', { name: '评论与交流' })).toBeVisible();
    await expect(page.getByText(/尚不能发表评论/).first()).toBeVisible();
    await expect(page.locator('.pc-example-label:visible').first()).toContainText('示例内容');
    await screenshot('detail-mobile');
    await element(page, 'pc-detail-back').click();
    await expect(page).toHaveURL(/#\/(?:pages\/)?community(?:\/index)?(?:[/?]|$)/);
    await waitForActivePage(page, 'community');
    await expect(element(page, 'pc-age-6-8')).toHaveAttribute('aria-pressed', 'true');
    await expect(element(page, 'pc-topic-parent-child')).toHaveAttribute('aria-pressed', 'true');
    await assertFiltered(chosen);
    await expect.poll(async () => Math.abs(await activeScroll() - scrollBefore)).toBeLessThanOrEqual(2);
    passed('Detail uses a returnable page stack and retains the 6–8 / parent-child filter and scroll');

    // Exercise a genuinely scrolled list as well as filter preservation; a single-card list can legitimately be at zero.
    await element(page, 'pc-age-all').click(); await element(page, 'pc-topic-all').click(); await assertFiltered(allPosts);
    const lastPost = allPosts.at(-1);
    await element(page, 'pc-open-' + lastPost.id).scrollIntoViewIfNeeded();
    const deepScroll = await activeScroll();
    assert.ok(deepScroll > 100, 'Scroll-return case must start below the first screen');
    await element(page, 'pc-open-' + lastPost.id).click(); await waitForActivePage(page, 'community/detail'); await expect(element(page, 'pc-detail-back')).toBeVisible();
    await element(page, 'pc-detail-back').click();
    await waitForActivePage(page, 'community');
    await expect.poll(activeScroll).toBeGreaterThan(deepScroll - 3);
    await expect.poll(activeScroll).toBeLessThan(deepScroll + 3);
    await element(page, 'pc-age-6-8').click(); await element(page, 'pc-topic-parent-child').click(); await assertFiltered(chosen);
    passed('Returning from the last fixture restores a nonzero list scroll position');

    await element(page, 'pc-compose-entry').click();
    await expect(page).toHaveURL(/community\/compose/);
    await waitForActivePage(page, 'community/compose');
    await expect(page.getByText('功能预览：目前不会发布到社区', { exact: false }).first()).toBeVisible();
    const titleInput = page.locator('input#pc-title-input:visible, #pc-title-input input:visible, [data-testid="pc-title-input"] input:visible').first();
    const bodyInput = page.locator('textarea#pc-body-input:visible, #pc-body-input textarea:visible, [data-testid="pc-body-input"] textarea:visible').first();
    await expect(titleInput).toBeVisible(); await expect(bodyInput).toBeVisible();
    await element(page, 'pc-compose-preview').click(); await expect(element(page, 'pc-compose-error')).toBeVisible();
    await titleInput.fill('   '); await bodyInput.fill('   '); await element(page, 'pc-compose-preview').click(); await expect(element(page, 'pc-compose-error')).toBeVisible();
    await titleInput.fill('合成标题'); await bodyInput.fill('合成正文');
    await element(page, 'pc-compose-preview').click(); await expect(element(page, 'pc-compose-error')).toContainText(/主动选择.*年龄段.*话题/);
    await element(page, 'pc-compose-age-9-12').click(); await element(page, 'pc-compose-topic-parent-growth').click();
    await titleInput.fill(''); await element(page, 'pc-compose-preview').click(); await expect(element(page, 'pc-compose-error')).toContainText('标题');
    await titleInput.fill('合成标题'); await bodyInput.fill(''); await element(page, 'pc-compose-preview').click(); await expect(element(page, 'pc-compose-error')).toContainText('正文');
    const titleLimit = 80, bodyLimit = 2000;
    await titleInput.fill('长'.repeat(titleLimit + 1)); await bodyInput.fill('合成正文');
    await element(page, 'pc-compose-preview').click(); await expect(element(page, 'pc-compose-error')).toContainText('标题最多 80 字');
    await titleInput.fill('合成标题'); await bodyInput.fill('文'.repeat(bodyLimit + 1));
    await element(page, 'pc-compose-preview').click(); await expect(element(page, 'pc-compose-error')).toContainText('正文最多 2000 字');
    await expect(element(page, 'pc-draft-preview')).toHaveCount(0);
    const syntheticTitle = '一次放学后的聊天（合成预览）';
    const syntheticBody = '<img src=x onerror="window.__pc01Injected=true">\n<script>window.__pc01Injected=true</script>\njavascript:alert(1)\n只是本地预览，没有真实孩子的信息。';
    await titleInput.fill(syntheticTitle); await bodyInput.fill(syntheticBody);
    await element(page, 'pc-compose-age-9-12').click(); await element(page, 'pc-compose-topic-parent-growth').click();
    await element(page, 'pc-compose-preview').click();
    await expect(element(page, 'pc-draft-preview')).toContainText(syntheticTitle); await expect(element(page, 'pc-draft-preview')).toContainText('<img src=x');
    assert.equal(await element(page, 'pc-draft-preview').locator('img, script, a[href^="javascript:"]').count(), 0, 'Untrusted draft text must not become HTML or executable links');
    assert.equal(await page.evaluate(() => window.__pc01Injected), undefined);
    await screenshot('compose-preview-mobile');
    await element(page, 'pc-compose-edit').click(); await expect(titleInput).toHaveValue(syntheticTitle); await expect(bodyInput).toHaveValue(syntheticBody);
    await expect(element(page, 'pc-compose-age-9-12')).toHaveAttribute('aria-pressed', 'true');
    await expect(element(page, 'pc-compose-topic-parent-growth')).toHaveAttribute('aria-pressed', 'true');
    await element(page, 'pc-compose-back').click(); await waitForActivePage(page, 'community'); await expect(element(page, 'pc-age-6-8')).toHaveAttribute('aria-pressed', 'true');
    await element(page, 'pc-compose-entry').click(); await waitForActivePage(page, 'community/compose'); await expect(titleInput).toHaveValue(syntheticTitle);
    await publicProbe();
    await page.reload({ waitUntil: 'networkidle' }); await waitForActivePage(page, 'community/compose'); await expect(titleInput).toHaveValue(''); await expect(bodyInput).toHaveValue('');
    await expect(element(page, 'pc-draft-preview')).toHaveCount(0);
    passed('Required fields, bounded input, pure-text preview, return-to-edit and memory-only draft cleared by reload', { title_limit: titleLimit, body_limit: bodyLimit });

    await publicProbe();
    await page.goto(preview.origin + '/#/community/detail?id=not-a-fixture', { waitUntil: 'networkidle' });
    await waitForActivePage(page, 'community/detail');
    await expect(element(page, 'pc-detail-missing')).toBeVisible(); await expect(element(page, 'pc-detail-back')).toBeVisible();
    await element(page, 'pc-detail-back').click(); await waitForActivePage(page, 'community'); await expect(element(page, 'nav-community')).toHaveAttribute('aria-current', 'page');
    passed('Unknown detail IDs have an honest missing state and a usable return path');

    for (const screen of SCREENS) {
      await page.setViewportSize(screen);
      for (const name of MAIN_PAGES) {
        evidence.current_step = `${name} ${screen.width}×${screen.height}`;
        await navigate(name);
        await expect(page.getByRole('main')).toHaveCount(1); await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
        await expect(page.getByRole('navigation').first()).toBeVisible();
        await assertNoOverflow(screen.width);
        if (screen.width === 600 || screen.width === 767) {
          const rail = await activeFrame(page).locator('.sc-rail').boundingBox();
          assert.ok(rail && Math.abs(rail.x) <= 1 && Math.abs(rail.width - screen.width) <= 1,
            'At the mobile navigation breakpoint, the rail must span the screen');
          assert.ok(Math.abs(rail.y + rail.height - screen.height) <= 1,
            'The mobile navigation must sit at the screen bottom, not remain a shortened sidebar');
          assert.equal(await activeFrame(page).locator('.sc-workspace').evaluate(node => getComputedStyle(node).marginLeft), '0px',
            'Mobile navigation must release the desktop workspace margin');
        }
        const targets = [];
        for (const destination of MAIN_PAGES) {
          const box = await element(page, 'nav-' + destination).boundingBox();
          assert.ok(box && box.width >= 43.5 && box.height >= 43.5, 'Main navigation targets must be at least 44px'); targets.push({ destination, width: box.width, height: box.height });
        }
        if (name === 'community') {
          for (const id of ['pc-age-6-8', 'pc-topic-parent-child', 'pc-compose-entry']) {
            await element(page, id).scrollIntoViewIfNeeded(); const box = await element(page, id).boundingBox();
            assert.ok(box && box.width >= 43.5 && box.height >= 43.5, 'Community filter/action target must be at least 44px');
            await element(page, id).click();
            if (id === 'pc-compose-entry') { await waitForActivePage(page, 'community/compose'); await expect(element(page, 'pc-compose-back')).toBeVisible(); await element(page, 'pc-compose-back').click(); await waitForActivePage(page, 'community'); }
          }
          // Screenshots represent the default feed, separately from the nonzero-scroll return test above.
          await element(page, 'pc-age-all').click(); await element(page, 'pc-topic-all').click(); await assertFiltered(allPosts);
          await activeFrame(page).evaluate(node => { node.scrollTop = 0; window.scrollTo(0, 0); });
          await expect.poll(activeScroll).toBe(0);
          await assertNoOverflow(screen.width);
        }
        evidence.responsive.push({ ...screen, page: name, document_width: await page.evaluate(() => document.documentElement.scrollWidth), navigation_targets: targets });
        if (name === 'community' || screen.width === 390) await screenshot(`${name}-${screen.width}`);
      }
    }
    passed('Four main pages, five required viewports plus 600/767px navigation breakpoints, functional filters, 44px targets and no horizontal overflow');

    await page.setViewportSize(SCREENS[0]); await navigate('community');
    await element(page, 'pc-age-3-5').focus(); await page.keyboard.press('Space'); await expect(element(page, 'pc-age-3-5')).toHaveAttribute('aria-pressed', 'true');
    const focus = await element(page, 'pc-age-3-5').evaluate(node => ({ focused: node.matches(':focus-visible'), style: getComputedStyle(node).outlineStyle, width: Number.parseFloat(getComputedStyle(node).outlineWidth) }));
    assert.ok(focus.focused && focus.style !== 'none' && focus.width >= 1, 'Keyboard filtering needs a visible focus outline');
    await element(page, 'nav-knowledge').focus(); await page.keyboard.press('Enter'); await expect(element(page, 'nav-knowledge')).toHaveAttribute('aria-current', 'page');
    await waitForActivePage(page, 'knowledge');
    await page.addStyleTag({ content: 'html { font-size: 32px !important; } .pc-shell--public :is(.pc-post-summary, .pc-filter-chip, .pc-form-hint, .sc-body-muted, .sc-nav-label, .pc-aside-text, .sc-page-description) { font-size: 32px !important; }' });
    await navigate('community');
    await element(page, 'pc-age-all').click(); await element(page, 'pc-topic-all').click();
    assert.equal(await cards(page).first().locator('.pc-post-summary').evaluate(node => Number.parseFloat(getComputedStyle(node).fontSize)), 32, 'Font enlargement must affect actual Chinese content');
    for (const name of MAIN_PAGES) { await navigate(name); await assertNoOverflow(375); }
    assert.equal(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), true);
    const motion = await page.locator('.pc-post-card:visible, .sc-nav-item:visible').evaluateAll(nodes => nodes.map(node => {
      const style = getComputedStyle(node); return { animation: style.animationName, duration: style.animationDuration, transition: style.transitionDuration };
    }));
    assert.ok(motion.every(value => (value.animation === 'none' || value.duration.split(',').every(duration => Number.parseFloat(duration) <= 0.01))
      && value.transition.split(',').every(duration => Number.parseFloat(duration) <= 0.01)), 'Reduced motion must eliminate substantial community/navigation animations');
    passed('Keyboard Space/Enter, visible focus, enlarged text and reduced-motion checks');

    await publicProbe();
    evidence.privacy = { network_violations: violations.length, public_page_errors: pageErrors.length, probe_snapshots: probes,
      private_api_requests: 0, media_permission_attempts: 0, publication_requests: 0, draft_persistence_writes: 0 };
    passed('Public routes never request camera/microphone, private API data, writes or draft persistence');

    // Legacy pages use a distinct fresh context: their documented read-only V1 requests do not weaken the public-page guard.
    const legacy = await browser.newContext({ viewport: SCREENS[1], reducedMotion: 'reduce', serviceWorkers: 'block' });
    await legacy.addInitScript(installPublicProbe);
    await legacy.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (allowedRequest(request.url(), request.method(), preview.origin, preview.staticPaths)) await route.continue();
      else if (url.origin === preview.origin && request.method() === 'GET' && url.pathname.startsWith('/api/v1/')) await route.abort('blockedbyclient');
      else { violations.push({ kind: 'legacy-unexpected-network', method: request.method() }); await route.abort('blockedbyclient'); }
    });
    await legacy.routeWebSocket('**', socket => { violations.push({ kind: 'legacy-websocket' }); socket.close(); });
    const legacyPage = await legacy.newPage();
    for (const name of ['session', 'insights', 'reports']) {
      await legacyPage.goto(preview.origin + '/#/growth', { waitUntil: 'networkidle' });
      await waitForActivePage(legacyPage, 'growth');
      await expect(element(legacyPage, 'pc-tool-' + name)).toBeVisible();
      await element(legacyPage, 'pc-tool-' + name).click();
      await expect(legacyPage).toHaveURL(new RegExp(`#/(?:pages/)?${name}(?:/index)?(?:[/?]|$)`));
      await waitForActivePage(legacyPage, name);
      await expect(legacyPage.getByRole('heading', { level: 1 })).toBeVisible();
      if (name === 'session') { await expect(element(legacyPage, 'session-start')).toBeVisible(); await expect(element(legacyPage, 'camera-status')).toContainText('Camera OFF'); }
      assert.equal(await legacyPage.evaluate(() => window.__pc01Probe.media), 0, 'Legacy page access alone must never start capture');
      await element(legacyPage, 'family-tools-back').click(); await waitForActivePage(legacyPage, 'growth'); await expect(element(legacyPage, 'nav-growth')).toHaveAttribute('aria-current', 'page');
    }
    assert.equal(violations.length, 0, 'Legacy accesses may not introduce remote APIs or writes');
    await legacy.close(); passed('Legacy Session / Insights / Reports remain directly accessible, without automatic device acquisition');
    evidence.status = 'pass';
  } catch (error) {
    failure = error; evidence.status = 'fail'; evidence.failure = { name: error.name, message: error.message };
    evidence.privacy = { ...evidence.privacy, network_violations: violations, public_page_errors: pageErrors.length, probe_snapshots: probes };
    if (inspectedPage && !inspectedPage.isClosed()) {
      try {
        const filename = path.join(run, 'failure.png');
        await inspectedPage.screenshot({ path: filename, fullPage: true, animations: 'disabled' });
        evidence.screenshots.push(filename);
        evidence.failure.route = new URL(inspectedPage.url()).hash.split('?')[0];
      } catch { evidence.failure.screenshot = 'unavailable'; }
    }
  } finally {
    try {
      if (browser) { await browser.close(); evidence.cleanup.push({ browser_closed: true }); }
      else evidence.cleanup.push({ browser_not_started: true });
    }
    catch (error) { failure ||= error; evidence.status = 'fail'; evidence.cleanup.push({ browser_closed: false }); }
    try {
      if (preview) { await preview.close(); evidence.cleanup.push({ owned_static_server_closed: true, port: preview.port, tcp_refused: true }); }
      else evidence.cleanup.push({ owned_static_server_not_started: true });
    }
    catch (error) { failure ||= error; evidence.status = 'fail'; evidence.cleanup.push({ owned_static_server_closed: false }); }
    evidence.finished_at = new Date().toISOString(); save();
  }
  if (failure) throw failure;
  console.log(`PC01 community acceptance: ${evidence.checks.length} checks passed; evidence ${path.join(OUTPUT, 'results.json')}`);
}

module.exports = { allowedRequest, knownStaticPaths, createPreview };
if (require.main === module) acceptance().catch(error => { console.error(error); process.exitCode = 1; });
