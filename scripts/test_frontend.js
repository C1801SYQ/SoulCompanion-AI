#!/usr/bin/env node
'use strict';
// Run the shipped product renderer with a small DOM, without browser dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');

class Element {
    constructor(tagName = 'div') {
        this.tagName = tagName.toUpperCase(); this.children = []; this.style = {}; this.dataset = {};
        this.attributes = {}; this.listeners = {}; this._text = ''; this.classes = new Set(); this.disabled = false;
        this.classList = {
            add: name => this.classes.add(name), remove: name => this.classes.delete(name),
            toggle: (name, force) => force ? this.classes.add(name) : this.classes.delete(name),
        };
    }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    set innerHTML(_value) { throw new Error('The renderer must not assign innerHTML'); }
    replaceChildren(...children) { this._text = ''; this.children = [...children]; }
    appendChild(child) { this.children.push(child); child.parentElement = this; return child; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name]; }
    removeAttribute(name) { delete this.attributes[name]; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    getBoundingClientRect() { return { width: 600, height: 200 }; }
    getContext() { return new Proxy({}, { get: () => () => {}, set: () => true }); }
    click() { if (this.listeners.click) return this.listeners.click(); }
    remove() {
        if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this);
    }
}
function harness({ mode = 'real', search = '', demoOnly = false } = {}) {
    const elements = new Map(), calls = [], blobs = [], downloads = [];
    const clock = { now: Date.now() };
    class ClockDate extends Date {
        constructor(...args) { super(...(args.length ? args : [clock.now])); }
        static now() { return clock.now; }
    }
    const getElementById = id => {
        if (!elements.has(id)) {
            const element = new Element();
            element.parentElement = new Element();
            elements.set(id, element);
        }
        return elements.get(id);
    };
    const body = new Element('body'); body.dataset.mode = mode; body.dataset.demoOnly = String(demoOnly);
    const buttons = [1, 7, 30].map(days => { const button = new Element('button'); button.dataset.days = String(days); return button; });
    const panels = ['snapshot', 'system', 'analytics', 'history', 'report', 'settings'].map(channel => {
        const panel = getElementById('panel-' + channel); panel.dataset.channel = channel; return panel;
    });
    const sandbox = {
        console: { error() {}, warn() {}, info() {} }, URLSearchParams, Date: ClockDate, Intl, AbortController, Blob,
        URL: { createObjectURL: blob => { blobs.push(blob); return 'blob:fixture/' + blobs.length; }, revokeObjectURL() {} },
        document: {
            body, hidden: false, getElementById, addEventListener() {},
            createElement: tag => {
                const element = new Element(tag);
                if (tag === 'a') element.click = () => downloads.push({ href: element.href, filename: element.download });
                return element;
            },
            querySelectorAll: selector => selector === '.range-btn' ? buttons
                : panels.filter(panel => selector === '[data-channel="' + panel.dataset.channel + '"]'),
        },
        location: { search }, addEventListener() {},
        setTimeout: () => 1, setInterval: () => 1, clearTimeout() {},
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(path.join(root, 'web/static/demo-data.js'), 'utf8'), sandbox);
    function fixture(url) {
        const data = JSON.parse(JSON.stringify(sandbox.SoulCompanionDemo.get(url)));
        if (data) data.mode = 'real';
        return data;
    }
    sandbox.fetch = async (url, options) => {
        calls.push({ url, signal: options.signal });
        if (url.includes('parent.md')) return { ok: true, headers: { get: () => 'text/markdown' }, blob: async () => new Blob(['# Real parent report']) };
        return { ok: true, json: async () => fixture(url) };
    };
    vm.runInContext(fs.readFileSync(path.join(root, 'web/static/app.js'), 'utf8'), sandbox);
    vm.runInContext('parseUrlFlags(); clearRenderedData(); renderConnectionState()', sandbox);
    return { sandbox, calls, elements, body, clock, blobs, downloads, buttons, panels, fixture,
        app: sandbox.SoulCompanionApp, get: getElementById, run: code => vm.runInContext(code, sandbox) };
}
async function main() {
    let passed = 0;
    const check = async (name, action) => { await action(); passed++; console.log('✓ ' + name); };
    await check('NORMAL REAL renders all resources; initial load sends six requests', async () => {
        const view = harness(); await view.app.refreshAll();
        assert.equal(view.calls.length, 6); assert.equal(view.body.dataset.connection, 'real');
        assert.equal(view.app.state.mode, 'real'); assert.ok(view.get('emotion-label').textContent);
        assert.equal(view.get('device-rows').children.length, 10); assert.match(view.get('setting-mode').textContent, /REAL/);
        assert.ok(view.get('chart-description').textContent.length > 20);
    });
    for (const options of [{ mode: 'demo' }, { search: '?demo=1' }]) {
        await check('explicit DEMO makes no backend requests: ' + JSON.stringify(options), async () => {
            const view = harness(options); await view.app.refreshAll();
            assert.equal(view.calls.length, 0); assert.equal(view.body.dataset.connection, 'demo');
            assert.equal(view.get('demo-badge').hidden, false);
            assert.ok(view.get('device-rows').children.every(row => row.dataset.status === 'disabled'));
        });
    }
    await check('OFFLINE never substitutes synthetic data', async () => {
        const view = harness(); view.sandbox.fetch = async () => { throw new TypeError('offline'); };
        await view.app.refreshAll();
        assert.equal(view.app.state.mode, 'real'); assert.equal(view.body.dataset.connection, 'offline');
        assert.match(view.get('connection-status').textContent, /Backend disconnected/);
        assert.equal(view.get('demo-badge').hidden, true);
        assert.match(view.get('risk-text').textContent, /未知/);
    });
    await check('last data is marked stale on disconnect, then refresh recovers', async () => {
        const view = harness(); await view.app.refreshAll();
        const label = view.get('emotion-label').textContent, healthy = view.sandbox.fetch;
        view.sandbox.fetch = async () => { throw new TypeError('offline'); };
        await view.app.refreshChannel('snapshot', true);
        assert.equal(view.get('emotion-label').textContent, label);
        assert.match(view.get('snapshot-state').textContent, /旧数据/);
        view.sandbox.fetch = healthy; await view.app.refreshChannel('snapshot', true);
        assert.equal(view.body.dataset.connection, 'real'); assert.equal(view.get('panel-snapshot').dataset.stale, 'false');
    });
    for (const response of [{ ok: false, status: 503 }, { ok: true, json: async () => { throw new SyntaxError('invalid JSON'); } }]) {
        await check('HTTP and invalid JSON are ERROR without DEMO', async () => {
            const view = harness(); view.sandbox.fetch = async () => response; await view.app.refreshAll();
            assert.equal(view.body.dataset.connection, 'error'); assert.equal(view.app.state.mode, 'real');
        });
    }
    await check('XSS payloads in reports, actions, history and settings remain text', async () => {
        const view = harness(), payload = '<img src=x onerror="globalThis.xss=true">';
        view.sandbox.fetch = async url => {
            const data = view.fixture(url);
            if (url.includes('/snapshot')) { data.behavior.actions = [payload]; data.emotion.emotional_cause = payload; }
            if (url.includes('/reports/parent?')) { data.highlights = [payload]; data.concerns = [payload]; data.suggestions = [payload]; data.summary = payload; }
            if (url.includes('/history?')) data.records[0].cause = payload;
            if (url.includes('/settings')) data.privacy_notice = payload;
            return { ok: true, json: async () => data };
        };
        await view.app.refreshAll();
        for (const id of ['behavior-actions', 'parent-highlights', 'parent-concerns', 'parent-suggestions']) {
            assert.equal(view.get(id).children[0].textContent, payload);
            assert.equal(view.get(id).children[0].children.length, 0);
        }
        assert.equal(view.get('privacy-notice').textContent, payload); assert.equal(view.sandbox.xss, undefined);
        assert.equal(view.get('history-rows').children[0].children[4].textContent, payload);
    });
    await check('unknown risk never claims a safe state', async () => {
        const view = harness();
        view.sandbox.fetch = async url => {
            const data = view.fixture(url);
            if (url.includes('/snapshot')) data.risk = { status: 'unknown', has_risk: null, triggers: [], checked_at: null };
            return { ok: true, json: async () => data };
        };
        await view.app.refreshAll();
        assert.match(view.get('risk-text').textContent, /未知/); assert.equal(view.get('risk-alert').dataset.risk, 'unknown');
    });
    await check('empty records, distribution and reports have meaningful empty states', async () => {
        const view = harness();
        view.sandbox.fetch = async url => {
            const data = view.fixture(url);
            if (url.includes('/history?')) { data.records = []; data.total = 0; data.has_more = false; }
            if (url.includes('/analytics?')) { data.counts = {}; data.total_records = 0; data.series = []; data.trend.total_records = 0; }
            if (url.includes('/reports/parent?')) {
                data.data_available = false; data.health_score = null; data.interaction_count = 0;
                data.highlights = []; data.concerns = []; data.suggestions = []; data.summary = '暂无记录';
            }
            return { ok: true, json: async () => data };
        };
        await view.app.refreshAll();
        assert.equal(view.get('health-score-text').textContent, '暂无数据');
        assert.equal(view.get('emotion-distribution').textContent, '暂无数据');
        assert.match(view.get('history-rows').textContent, /暂无记录/);
        assert.equal(view.get('history-next').disabled, true);
    });
    await check('never-settling fetch times out, releases its channel and recovers', async () => {
        const view = harness(), healthy = view.sandbox.fetch, signals = [];
        view.sandbox.setTimeout = setTimeout; view.sandbox.clearTimeout = clearTimeout; view.app.config.requestTimeout = 10;
        view.sandbox.fetch = (_url, options) => { signals.push(options.signal); return new Promise(() => {}); };
        await view.app.refreshAll();
        assert.ok(Object.values(view.app.channels).every(channel => !channel.inFlight));
        assert.ok(signals.every(signal => signal.aborted)); assert.equal(view.body.dataset.connection, 'offline');
        view.sandbox.fetch = healthy; await view.app.refreshAll(true);
        assert.equal(view.body.dataset.connection, 'real');
    });
    await check('never-settling JSON body also reaches the request deadline', async () => {
        const view = harness();
        view.sandbox.setTimeout = setTimeout; view.sandbox.clearTimeout = clearTimeout; view.app.config.requestTimeout = 10;
        view.sandbox.fetch = async () => ({ ok: true, json: () => new Promise(() => {}) });
        await view.app.refreshAll();
        assert.equal(view.app.channels.snapshot.inFlight, false); assert.equal(view.body.dataset.connection, 'offline');
    });
    await check('new history range replaces previous range failures', async () => {
        const view = harness(), healthy = view.sandbox.fetch;
        await view.app.refreshAll();
        view.sandbox.fetch = async () => ({ ok: false, status: 503 }); await view.app.setHistoryRange(7);
        assert.equal(view.app.channels.history.error, 'ERROR');
        view.sandbox.fetch = healthy; await view.app.setHistoryRange(30);
        assert.equal(view.app.channels.history.error, null); assert.equal(view.app.channels.analytics.error, null);
        assert.equal(view.app.channels.history.data.days, 30);
    });
    for (const reject of [true, false]) {
        await check('old-range ' + (reject ? 'failure' : 'response') + ' cannot overwrite a newer range', async () => {
            const view = harness(), healthy = view.sandbox.fetch;
            let resolveOld, rejectOld;
            view.sandbox.fetch = async (url, options) => {
                if (url.includes('/history?days=1')) return new Promise((resolve, failure) => { resolveOld = resolve; rejectOld = failure; });
                return healthy(url, options);
            };
            const pending = view.app.refreshChannel('history', true);
            await view.app.setHistoryRange(7);
            assert.notEqual(view.app.channels.history.data, null, 'New range failed: ' + view.app.channels.history.error);
            if (reject) rejectOld(new TypeError('obsolete'));
            else resolveOld({ ok: true, json: async () => view.fixture('/api/v1/emotions/history?days=1&limit=20&offset=0') });
            await pending;
            assert.equal(view.app.channels.history.data.days, 7); assert.equal(view.app.channels.history.error, null);
        });
    }
    await check('REAL with nullable sensor data displays no invented neutral or confidence', async () => {
        const view = harness();
        view.sandbox.fetch = async url => {
            const data = view.fixture(url);
            if (url.includes('/snapshot')) { data.data_available = false; data.emotion = null; data.behavior = null; }
            return { ok: true, json: async () => data };
        };
        await view.app.refreshAll();
        assert.equal(view.get('emotion-label').textContent, '暂无感知数据');
        assert.equal(view.get('confidence-value').textContent, '--'); assert.equal(view.get('valence-value').textContent, '--');
        assert.match(view.get('connection-status').textContent, /REAL.*暂无感知数据/);
    });
    for (const invalid of [null, 'bad', Infinity, -1, 2]) {
        await check('malformed confidence is rejected before rendering: ' + String(invalid), async () => {
            const view = harness();
            view.sandbox.fetch = async url => {
                const data = view.fixture(url);
                if (url.includes('/snapshot')) data.emotion.confidence = invalid;
                return { ok: true, json: async () => data };
            };
            await view.app.refreshAll(); assert.equal(view.body.dataset.connection, 'error');
            assert.equal(view.get('confidence-value').textContent, '--');
        });
    }
    await check('malformed report lists do not stop the independent snapshot channel', async () => {
        const view = harness();
        view.sandbox.fetch = async url => {
            const data = view.fixture(url);
            if (url.includes('/reports/parent?')) data.highlights = 'invalid';
            return { ok: true, json: async () => data };
        };
        await view.app.refreshAll();
        assert.equal(view.app.channels.report.error, 'ERROR'); assert.equal(view.body.dataset.connection, 'real');
    });
    await check('history pagination is isolated and range change resets offset', async () => {
        const view = harness(); await view.app.refreshAll(); await view.app.setHistoryRange(7);
        assert.equal(view.app.channels.history.data.has_more, true);
        await view.app.changeHistoryPage(1); assert.equal(view.app.state.historyOffset, 20);
        assert.equal(view.app.channels.history.data.offset, 20);
        await view.app.changeHistoryPage(-1); assert.equal(view.app.state.historyOffset, 0);
        await view.app.changeHistoryPage(1); await view.app.setHistoryRange(30);
        assert.equal(view.app.state.historyOffset, 0); assert.equal(view.buttons[2].getAttribute('aria-pressed'), 'true');
    });
    await check('slow report does not block live snapshots or snapshot risk updates', async () => {
        const view = harness(), healthy = view.sandbox.fetch;
        let resolveReport;
        view.sandbox.fetch = async (url, options) => {
            if (url.includes('/reports/parent?')) return new Promise(resolve => { resolveReport = resolve; });
            return healthy(url, options);
        };
        const report = view.app.refreshChannel('report', true);
        await view.app.refreshChannel('snapshot', true);
        assert.equal(view.app.channels.report.inFlight, true); assert.equal(view.body.dataset.connection, 'real');
        assert.equal(view.app.channels.snapshot.inFlight, false);
        resolveReport({ ok: true, json: async () => view.fixture('/api/v1/reports/parent?days=7') }); await report;
    });
    await check('mode switch aborts REAL requests, discards late results, then reconnects REAL', async () => {
        const view = harness(), healthy = view.sandbox.fetch, signals = [];
        let resolveReal;
        view.sandbox.fetch = (_url, options) => { signals.push(options.signal); return new Promise(resolve => { resolveReal = resolve; }); };
        const pending = view.app.refreshChannel('snapshot', true);
        await view.app.setMode('demo');
        assert.ok(signals.every(signal => signal.aborted)); assert.equal(view.app.state.mode, 'demo');
        resolveReal({ ok: true, json: async () => view.fixture('/api/v1/dashboard/snapshot') }); await pending;
        assert.equal(view.body.dataset.connection, 'demo');
        view.sandbox.fetch = healthy; await view.app.setMode('real'); assert.equal(view.body.dataset.connection, 'real');
    });
    await check('static DEMO-only ignores nodemo and refuses REAL connection', async () => {
        const view = harness({ mode: 'demo', demoOnly: true, search: '?nodemo=1' });
        await view.app.refreshAll(); await view.app.setMode('real');
        assert.equal(view.app.state.mode, 'demo'); assert.equal(view.calls.length, 0);
    });
    await check('DEMO export downloads a labelled synthetic Markdown Blob without HTTP', async () => {
        const view = harness({ mode: 'demo' }); await view.app.refreshAll(); await view.app.exportReport();
        assert.equal(view.calls.length, 0); assert.equal(view.downloads.length, 1);
        assert.match(view.downloads[0].filename, /demo/); assert.match(await view.blobs[0].text(), /DEMO DATA/);
    });
    await check('REAL export fetches Markdown as a Blob', async () => {
        const view = harness(); await view.app.exportReport();
        assert.equal(view.calls.length, 1); assert.match(view.calls[0].url, /parent\.md\?days=7/);
        assert.equal(await view.blobs[0].text(), '# Real parent report');
    });
    await check('report range is independent from history and analytics range', async () => {
        const view = harness(); await view.app.refreshAll(); const before = view.calls.length;
        await view.app.setReportRange(30);
        assert.equal(view.calls.length - before, 1); assert.equal(view.app.state.historyDays, 1);
        assert.match(view.calls[view.calls.length - 1].url, /reports\/parent\?days=30/);
    });
    await check('range change cancels a pending Markdown body instead of mislabelling the download', async () => {
        const view = harness(), healthy = view.sandbox.fetch;
        let resolveBody, exportSignal;
        view.sandbox.fetch = async (url, options) => {
            if (url.includes('/parent.md')) {
                exportSignal = options.signal;
                return { ok: true, headers: { get: () => 'text/markdown' },
                    blob: () => new Promise(resolve => { resolveBody = resolve; }) };
            }
            return healthy(url, options);
        };
        const pending = view.app.exportReport();
        await new Promise(resolve => setImmediate(resolve));
        await view.app.setReportRange(30);
        assert.equal(exportSignal.aborted, true);
        resolveBody(new Blob(['7-day report']));
        assert.equal(await pending, false);
        assert.equal(view.downloads.length, 0);
        view.sandbox.fetch = healthy;
        await view.app.exportReport();
        assert.match(view.downloads[0].filename, /30d\.md$/);
    });
    await check('browser DEMO explains background capture while static DEMO has no backend', async () => {
        const browser = harness({ mode: 'demo' }); await browser.app.refreshAll();
        assert.match(browser.get('privacy-notice').textContent, /不会停止后台/);
        assert.match(browser.get('setting-raw').textContent, /后台策略/);
        const staticDemo = harness({ mode: 'demo', demoOnly: true }); await staticDemo.app.refreshAll();
        assert.match(staticDemo.get('setting-api').textContent, /不连接后端/);
        assert.equal(staticDemo.get('setting-raw').textContent, '不保存原始文本');
    });
    await check('failed new report range clears every old score, list and period', async () => {
        const view = harness(); await view.app.refreshAll();
        assert.notEqual(view.get('health-score-text').textContent, '--');
        view.sandbox.fetch = async () => ({ ok: false, status: 503 });
        const pending = view.app.setReportRange(30);
        assert.equal(view.get('health-score-text').textContent, '--');
        assert.equal(view.get('report-period').textContent, '');
        await pending;
        assert.match(view.get('parent-summary').textContent, /未能获取所选范围/);
        for (const id of ['parent-highlights', 'parent-concerns', 'parent-suggestions'])
            assert.equal(view.get(id).textContent, '暂无所选范围数据');
        assert.match(view.get('report-state').textContent, /暂无可用数据/);
    });
    await check('failed new history range clears old trend statistics and distribution', async () => {
        const view = harness(); await view.app.refreshAll();
        assert.notEqual(view.get('trend-count').textContent, '--');
        view.sandbox.fetch = async () => ({ ok: false, status: 503 });
        await view.app.setHistoryRange(30);
        for (const id of ['trend-dominant', 'trend-valence', 'trend-stability', 'trend-count'])
            assert.equal(view.get(id).textContent, '--');
        assert.equal(view.get('emotion-distribution').textContent, '暂无数据');
        assert.match(view.get('chart-description').textContent, /未能获取所选范围/);
        assert.equal(view.get('history-rows').children.length, 0);
    });
    await check('retention policy explicitly says cleanup is manual', async () => {
        const view = harness();
        view.sandbox.fetch = async url => {
            const data = view.fixture(url); data.storage.retention_days = 30;
            return { ok: true, json: async () => data };
        };
        await view.app.refreshChannel('settings', true);
        assert.equal(view.get('setting-retention').textContent, '30 天，需手动清理');
    });
    await check('settings storage follows the completed database probe without extra requests', async () => {
        const view = harness();
        let resolveSystem, requests = 0;
        view.sandbox.fetch = async url => {
            requests++;
            const data = view.fixture(url);
            if (url.includes('/system/status')) {
                data.components.database.status = 'healthy';
                return new Promise(resolve => { resolveSystem = () => resolve({ ok: true, json: async () => data }); });
            }
            data.storage.status = 'unknown';
            return { ok: true, json: async () => data };
        };
        const pending = view.app.refreshChannel('system', true);
        await view.app.refreshChannel('settings', true);
        assert.match(view.get('setting-storage').textContent, /未知/);
        resolveSystem(); await pending;
        assert.match(view.get('setting-storage').textContent, /正常/);
        assert.equal(requests, 2);
        await view.app.refreshChannel('settings', true);
        assert.match(view.get('setting-storage').textContent, /正常/);
        view.sandbox.fetch = async () => ({ ok: false, status: 503 });
        await view.app.refreshChannel('system', true);
        assert.match(view.get('setting-storage').textContent, /未知/);
    });
    await check('steady snapshot is one request each second; historical cadence stays low', async () => {
        const view = harness(); await view.app.refreshAll(); const startup = view.calls.length;
        for (let second = 1; second <= 60; second++) { view.clock.now += 1000; await view.app.refreshAll(); }
        const byPath = {};
        view.calls.slice(startup).forEach(call => { const resource = call.url.split('?')[0]; byPath[resource] = (byPath[resource] || 0) + 1; });
        assert.equal(byPath['/api/v1/dashboard/snapshot'], 60); assert.equal(byPath['/api/v1/system/status'], 8);
        assert.equal(byPath['/api/v1/emotions/analytics'], 2); assert.equal(byPath['/api/v1/emotions/history'], 2);
        assert.equal(byPath['/api/v1/reports/parent'], 1); assert.equal(byPath['/api/v1/system/settings'], undefined);
        assert.equal(view.calls.length - startup, 73);
    });
    await check('duplicate scheduled refresh does not overlap a pending channel', async () => {
        const view = harness(); let resolvePending; let starts = 0;
        view.sandbox.fetch = () => { starts++; return new Promise(resolve => { resolvePending = resolve; }); };
        const pending = view.app.refreshChannel('snapshot');
        await view.app.refreshChannel('snapshot'); assert.equal(starts, 1);
        resolvePending({ ok: true, json: async () => view.fixture('/api/v1/dashboard/snapshot') }); await pending;
    });
    await check('outdated sensor source and stale risk are displayed as unavailable or unknown', async () => {
        const view = harness();
        view.sandbox.fetch = async url => {
            const data = view.fixture(url);
            if (url.includes('/snapshot')) {
                data.bridge.last_update = new Date(view.clock.now - 30000).toISOString();
                data.risk.checked_at = new Date(view.clock.now - 30000).toISOString();
            }
            return { ok: true, json: async () => data };
        };
        await view.app.refreshAll();
        assert.equal(view.get('emotion-label').textContent, '暂无感知数据'); assert.match(view.get('source-time').textContent, /过期/);
        assert.equal(view.get('risk-alert').dataset.risk, 'unknown');
    });
    console.log('Frontend DOM checks: ' + passed + ' passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
