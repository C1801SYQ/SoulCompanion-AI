/** Browser acceptance against the actual local API and an isolated synthetic SQLite history. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const { randomUUID } = require('node:crypto');
const { spawn, spawnSync } = require('node:child_process');
const { once } = require('node:events');
const { chromium, expect } = require('@playwright/test');
const ROOT = path.resolve(__dirname, '..');
const OUTPUT = path.join(ROOT, '.test-artifacts', 'browser-acceptance');
const python = process.env.SOULCOMPANION_PYTHON || 'python';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const evidence = { status: 'running', fixture: 'synthetic test history through actual SQLite and HTTP API', checks: [] };
const children = new Set();
const hasExited = child => child.exitCode !== null || child.signalCode !== null;

async function waitPortClosed(url) {
    const address = new URL(url), deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
        const closed = await new Promise((resolve, reject) => {
            const socket = net.createConnection({ host: '127.0.0.1', port: Number(address.port) });
            socket.once('connect', () => { socket.destroy(); resolve(false); });
            socket.once('error', error => { socket.destroy(); if (error.code === 'ECONNREFUSED') resolve(true); else reject(error); });
            // Windows may need about two seconds to report ECONNREFUSED.
            // A timeout remains inconclusive, so retry without accepting it as closure.
            const remaining = Math.max(1, Math.min(3000, deadline - Date.now()));
            socket.setTimeout(remaining, () => { socket.destroy(); resolve(false); });
        });
        if (closed) return;
        await delay(100);
    }
    throw new Error('Acceptance TCP port closure could not be verified');
}

async function freePort() {
    const socket = net.createServer();
    socket.listen(0, '127.0.0.1');
    await once(socket, 'listening');
    const port = socket.address().port;
    await new Promise(resolve => socket.close(resolve));
    return port;
}
async function runServer(args, url) {
    const stopFile = args[0] === 'scripts/acceptance_server.py'
        ? path.join(OUTPUT, 'stop-' + randomUUID() + '.signal') : null;
    if (stopFile) args = [...args, '--stop-file', stopFile];
    const log = fs.openSync(path.join(OUTPUT, 'backend.log'), 'a');
    const child = spawn(python, args, { cwd: ROOT, windowsHide: true,
        env: { ...process.env, PYTHONUTF8: '1' }, stdio: ['ignore', log, log] });
    fs.closeSync(log);
    child.acceptanceStopFile = stopFile;
    child.acceptanceUrl = url;
    children.add(child);
    let spawnError;
    child.on('error', error => { spawnError = error; });
    try {
        for (let attempt = 0; attempt < 100; attempt++) {
            if (spawnError) throw spawnError;
            if (hasExited(child)) throw new Error('Acceptance server exited; see backend.log');
            try {
                const response = await fetch(url, { signal: AbortSignal.timeout(1000) });
                if (response.ok) return child;
            } catch { /* A newly spawned local server is not listening yet. */ }
            await delay(100);
        }
        throw new Error('Acceptance server startup timed out');
    } catch (error) {
        await stop(child);
        throw error;
    }
}
async function stop(child) {
    if (!child || !children.has(child)) return;
    if (!child.pid) { children.delete(child); return; }
    if (!hasExited(child)) {
        if (child.acceptanceStopFile) fs.writeFileSync(child.acceptanceStopFile, 'stop', { flag: 'wx' });
        else child.kill();
        await Promise.race([once(child, 'exit'), delay(5000)]);
        if (!hasExited(child)) {
            child.kill('SIGKILL');
            await Promise.race([once(child, 'exit'), delay(5000)]);
            if (!hasExited(child)) throw new Error('Acceptance child did not stop');
        }
    }
    if (child.acceptanceStopFile) await waitPortClosed(child.acceptanceUrl);
    if (child.acceptanceStopFile) fs.rmSync(child.acceptanceStopFile, { force: true });
    children.delete(child);
}
function passed(message) {
    evidence.checks.push(message);
    process.stdout.write('PASS ' + message + '\n');
}
async function downloadText(page, button, filename) {
    const pending = page.waitForEvent('download');
    await page.locator(button).click();
    const download = await pending;
    const target = path.join(OUTPUT, filename);
    await download.saveAs(target);
    return fs.readFileSync(target, 'utf8');
}
async function main() {
    fs.mkdirSync(OUTPUT, { recursive: true });
    fs.writeFileSync(path.join(OUTPUT, 'results.json'), JSON.stringify(evidence, null, 2) + '\n');
    const fixture = fs.mkdtempSync(path.join(OUTPUT, 'fixture-'));
    const database = path.join(fixture, 'acceptance.sqlite');
    const port = await freePort(), base = `http://127.0.0.1:${port}`;
    let backend, browser;
    try {
        backend = await runServer(['scripts/acceptance_server.py', '--port', String(port), '--db', database, '--seed'], base + '/healthz');
        browser = await chromium.launch({ headless: true });
        const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
        const page = await context.newPage();
        const fatal = [], consoleErrors = [], requests = [];
        let inFlight = 0, maximumInFlight = 0;
        page.on('pageerror', error => fatal.push(error.message));
        page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
        page.on('request', request => {
            if (request.url().includes('/api/')) requests.push({ url: request.url(), time: Date.now() });
            if (request.url().includes('/dashboard/snapshot')) { inFlight++; maximumInFlight = Math.max(maximumInFlight, inFlight); }
        });
        const finished = request => { if (request.url().includes('/dashboard/snapshot')) inFlight--; };
        page.on('requestfinished', finished); page.on('requestfailed', finished);
        await page.goto(base);
        await expect(page.locator('#connection-status')).toContainText('REAL', { timeout: 20000 });
        await expect(page.locator('#history-summary')).toContainText('65 条');
        await expect(page.locator('#history-rows tr')).toHaveCount(20);
        await expect(page.locator('#device-rows tr')).toHaveCount(10);
        await expect(page.locator('#emotion-label')).toHaveText('暂无感知数据');
        await expect(page.locator('#risk-text')).toContainText('未知');
        await expect(page.locator('#setting-scope')).toContainText('仅本机访问');
        await expect(page.locator('#parent-summary')).not.toHaveText('加载中...');
        assert.deepEqual(consoleErrors, []);
        passed('REAL connects to actual API; SQLite history, report, ten device states and empty live state render');

        const before = requests.length;
        await delay(5200);
        const round = requests.slice(before);
        const snapshots = round.filter(request => request.url.includes('/dashboard/snapshot')).length;
        assert.ok(snapshots >= 4 && snapshots <= 7, 'Realtime should poll approximately once per second');
        assert.equal(round.filter(request => /emotions\/(history|analytics)|reports\//.test(request.url)).length, 0);
        assert.equal(maximumInFlight, 1);
        evidence.realtime = { seconds: 5.2, snapshot_requests: snapshots, historical_requests: 0, maximum_snapshot_in_flight: maximumInFlight };
        passed('Realtime uses one snapshot per second; history/report remain idle and snapshot requests do not overlap');

        await page.locator('#history-next').click();
        await expect(page.locator('#history-summary')).toContainText('第 21–40 条');
        await page.locator('#history-prev').click();
        await expect(page.locator('#history-summary')).toContainText('第 1–20 条');
        await page.locator('[data-days="30"]').click();
        await expect(page.locator('#history-summary')).toContainText('30天');
        await page.locator('#report-range').selectOption('30');
        await expect(page.locator('#report-state')).toContainText('更新于');
        const realReport = await downloadText(page, '#report-export', 'parent-real.md');
        assert.ok(realReport.length > 100 && !realReport.includes('DEMO DATA'));
        passed('History range/pagination and real historical Markdown export work');
        await page.screenshot({ path: path.join(OUTPUT, 'desktop-real.png'), fullPage: true });

        for (const width of [375, 768, 1440]) {
            await page.setViewportSize({ width, height: 900 });
            await delay(250);
            const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
            assert.equal(overflow, false, `Page overflows at ${width}px`);
            await page.screenshot({ path: path.join(OUTPUT, `responsive-${width}.png`), fullPage: true });
            if (width === 375) {
                await page.locator('h1').scrollIntoViewIfNeeded();
                await page.screenshot({ path: path.join(OUTPUT, 'mobile-top.png') });
            }
        }
        await page.locator('#mode-demo').focus();
        await page.keyboard.press('Enter');
        await expect(page.locator('#connection-status')).toContainText('DEMO DATA');
        await expect(page.locator('#emotion-label')).not.toHaveText('暂无感知数据');
        await delay(250);
        const demoStart = requests.length;
        await delay(2200);
        assert.equal(requests.length, demoStart);
        const demoReport = await downloadText(page, '#report-export', 'parent-demo.md');
        assert.ok(demoReport.includes('DEMO DATA'));
        passed('375/768/1440px layouts have no page overflow; keyboard selects explicit DEMO with zero API requests and labelled export');
        await page.screenshot({ path: path.join(OUTPUT, 'desktop-demo.png'), fullPage: true });

        await page.locator('#mode-real').click();
        await expect(page.locator('#connection-status')).toContainText('REAL');
        await page.route('**/api/v1/dashboard/snapshot', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{"mode":"real"}' }));
        await page.locator('#retry-connection').click();
        await expect(page.locator('#connection-status')).toContainText('ERROR');
        await expect(page.locator('#demo-badge')).toBeHidden();
        await page.unroute('**/api/v1/dashboard/snapshot');
        await page.locator('#retry-connection').click();
        await expect(page.locator('#connection-status')).toContainText('REAL');
        passed('Malformed API contract becomes ERROR and recovers without switching to DEMO');

        await stop(backend); backend = null;
        await expect(page.locator('#connection-status')).toContainText('Backend disconnected', { timeout: 20000 });
        await expect(page.locator('#mode-real')).toHaveAttribute('aria-pressed', 'true');
        await expect(page.locator('#demo-badge')).toBeHidden();
        await expect(page.locator('#risk-text')).toContainText('未知');
        await page.screenshot({ path: path.join(OUTPUT, 'offline.png'), fullPage: true });
        backend = await runServer(['scripts/acceptance_server.py', '--port', String(port), '--db', database], base + '/healthz');
        await page.locator('#retry-connection').click();
        await expect(page.locator('#connection-status')).toContainText('REAL');
        const refreshedHistory = page.waitForResponse(response =>
            response.url().includes('/api/v1/emotions/history?') && response.request().method() === 'GET');
        await page.locator('#history-refresh').click();
        const historyResponse = await refreshedHistory;
        assert.equal(historyResponse.status(), 200);
        const persistedHistory = await historyResponse.json();
        assert.equal(persistedHistory.total, 65);
        assert.ok(persistedHistory.records.length > 0);
        await expect(page.locator('#history-state')).toContainText('更新于');
        await expect(page.locator('#history-summary')).toContainText('65 条');
        passed('Backend stop shows OFFLINE; restart restores REAL and persisted records');

        const staticDirectory = path.join(fixture, 'site');
        const built = spawnSync(python, ['scripts/build_site.py', '--out', staticDirectory], {
            cwd: ROOT, windowsHide: true, env: { ...process.env, PYTHONUTF8: '1' }, encoding: 'utf8' });
        assert.equal(built.status, 0, built.stderr);
        const staticPort = await freePort(), staticBase = `http://127.0.0.1:${staticPort}`;
        const staticServer = await runServer(['scripts/acceptance_server.py', '--port', String(staticPort), '--static-dir', staticDirectory], staticBase);
        const staticPage = await context.newPage();
        const staticApi = [];
        staticPage.on('pageerror', error => fatal.push(error.message));
        staticPage.on('request', request => { if (request.url().includes('/api/')) staticApi.push(request.url()); });
        await staticPage.goto(staticBase + '/?nodemo=1');
        await expect(staticPage.locator('#connection-status')).toContainText('DEMO DATA');
        await expect(staticPage.locator('#mode-real')).toBeDisabled();
        await delay(1200);
        assert.deepEqual(staticApi, []);
        await stop(staticServer);
        passed('Static build is DEMO-only even with nodemo query; no backend/data access');
        assert.deepEqual(fatal, []);
        evidence.console_fatal_errors = fatal;
        passed('Browser has zero fatal console exceptions');
        evidence.status = 'passed';
    } catch (error) {
        evidence.status = 'failed';
        evidence.failure = error.message;
        throw error;
    } finally {
        const cleanupErrors = [];
        if (browser) {
            try { await browser.close(); } catch (error) { cleanupErrors.push(error); }
        }
        for (const child of new Set([backend, ...children])) {
            try { await stop(child); } catch (error) { cleanupErrors.push(error); }
        }
        if (cleanupErrors.length) {
            evidence.status = 'failed';
            evidence.cleanup_errors = cleanupErrors.map(error => error.message);
        }
        fs.writeFileSync(path.join(OUTPUT, 'results.json'), JSON.stringify(evidence, null, 2) + '\n');
        if (cleanupErrors.length) throw new AggregateError(cleanupErrors, 'Browser acceptance cleanup failed');
    }
}
main().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
