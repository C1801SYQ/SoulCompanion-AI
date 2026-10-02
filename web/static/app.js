/**
 * Vanilla product UI. Independent channels isolate historical work from live data.
 */
'use strict';
const CONFIG = { refreshInterval: 1000, systemInterval: 7000, historyInterval: 30000,
    reportInterval: 60000, requestTimeout: 5000, pageSize: 20, apiBase: '/api/v1' };
const EMOTION_MAP = {
    happy: { icon: '😊', label: '开心', color: '#856000' }, calm: { icon: '😌', label: '平静', color: '#226275' },
    neutral: { icon: '😐', label: '中性', color: '#23752b' }, surprised: { icon: '😮', label: '惊讶', color: '#8c4b00' },
    anxious: { icon: '😰', label: '焦虑', color: '#8c4b00' }, sad: { icon: '😢', label: '难过', color: '#43518e' },
    angry: { icon: '😠', label: '生气', color: '#aa2828' }, fearful: { icon: '😨', label: '害怕', color: '#68518c' },
    distressed: { icon: '😵', label: '过载', color: '#a3350d' },
};
const ACTION_LABELS = {
    heartbeat: '💓 心跳模拟', breathing_led: '💡 呼吸灯', ear_wiggle: '👂 耳朵摆动', head_tilt: '🤔 好奇歪头',
    soothing_voice: '🗣️ 温柔语音', excited_voice: '🗣️ 欢快语音', slow_motion: '🦽 缓慢运动', still: '🧊 静止模式',
    led_warm: '💡 暖色灯', led_cool: '💡 冷色灯', led_dim: '💡 柔光灯',
};
const COMPONENT_LABELS = {
    backend: 'Backend / 后端', database: 'Database / 数据库', bridge: 'Bridge / 桥接', camera: 'Camera / 摄像头',
    microphone: 'Microphone / 麦克风', vision_model: 'Vision model / 视觉模型', speech_model: 'Speech model / 语音模型',
    ser_model: 'SER model / 语音情绪模型', ollama: 'Ollama', hardware: 'Hardware / 硬件',
};
const STATUS_LABELS = { healthy: '正常', degraded: '降级', unavailable: '不可用', disabled: '未启用', unknown: '未知' };
const state = { mode: 'real', demoOnly: false, epoch: 0, historyDays: 1, reportDays: 7,
    historyOffset: 0, started: false, timer: null };
const intervals = { snapshot: CONFIG.refreshInterval, system: CONFIG.systemInterval,
    analytics: CONFIG.historyInterval, history: CONFIG.historyInterval, report: CONFIG.reportInterval,
    settings: 0, export: 0 };
const channels = Object.fromEntries(Object.entries(intervals).map(([name, interval]) =>
    [name, { interval, generation: 0, controller: null, inFlight: false, nextAt: 0, lastAt: 0,
        failures: 0, error: null, data: null }]));
const $ = id => document.getElementById(id);
function text(id, value) {
    const element = $(id);
    if (element && element.textContent !== String(value)) element.textContent = String(value);
}
function node(tag, value, className) {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = String(value);
    if (className) element.className = className;
    return element;
}
function emotionInfo(category) {
    return Object.hasOwn(EMOTION_MAP, category) ? EMOTION_MAP[category]
        : { icon: '❔', label: category === 'unknown' ? '未知' : String(category), color: '#555' };
}
function renderTextItems(container, values, tag, className, fallback) {
    if (!container) return;
    container.replaceChildren();
    (values.length ? values : [fallback]).forEach(value => container.appendChild(node(tag, value, className)));
}
function milliseconds(value) { return typeof value === 'string' ? Date.parse(value.replace(/(\.\d{3})\d+/, '$1')) : NaN; }
function formatTime(value) {
    const stamp = milliseconds(value);
    return Number.isFinite(stamp) ? new Date(stamp).toLocaleString('zh-CN', { hour12: false }) : '--';
}
function fresh(value, maximumAge = 15000) {
    const age = Date.now() - milliseconds(value);
    return Number.isFinite(age) && age >= -5000 && age <= maximumAge;
}
function zoneLabel() { return Intl.DateTimeFormat().resolvedOptions().timeZone || '本机时区'; }
function requireValue(condition) { if (!condition) throw new Error('API response does not match the product contract'); }
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const number = (value, min = -Infinity, max = Infinity) =>
    typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max;
const integer = value => Number.isInteger(value) && value >= 0;
const strings = value => Array.isArray(value) && value.every(item => typeof item === 'string');
const timestamp = value => typeof value === 'string' && Number.isFinite(milliseconds(value));
function checkEmotion(value) {
    requireValue(object(value) && typeof value.category === 'string' && number(value.confidence, 0, 1)
        && number(value.valence, -1, 1) && number(value.arousal, 0, 1)
        && number(value.attention_level, 0, 1) && timestamp(value.timestamp));
    ['vision_emotion', 'speech_emotion', 'environment_signal', 'emotional_cause']
        .forEach(key => requireValue(typeof value[key] === 'string'));
}
function checkBehavior(value) {
    requireValue(object(value) && strings(value.actions) && number(value.speech_rate, 0)
        && number(value.led_brightness, 0, 1) && number(value.servo_speed, 0, 1)
        && typeof value.led_color === 'string' && typeof value.reason === 'string');
}
function checkTrend(value) {
    requireValue(object(value) && typeof value.period === 'string' && typeof value.dominant_emotion === 'string'
        && number(value.average_valence, -1, 1) && number(value.average_arousal, 0, 1)
        && number(value.stability_score, 0, 1) && integer(value.total_records)
        && strings(value.risk_periods) && strings(value.positive_periods));
}
function checkResponse(name, data) {
    requireValue(object(data) && data.mode === state.mode);
    if (name === 'snapshot') {
        requireValue(timestamp(data.timestamp) && typeof data.data_available === 'boolean'
            && object(data.risk) && ['known', 'unknown'].includes(data.risk.status)
            && strings(data.risk.triggers) && object(data.bridge) && object(data.system));
        requireValue(data.risk.status === 'known' ? typeof data.risk.has_risk === 'boolean'
            && timestamp(data.risk.checked_at) : data.risk.has_risk === null);
        requireValue(typeof data.bridge.connected === 'boolean' && typeof data.bridge.running === 'boolean'
            && integer(data.bridge.cycle_count) && (data.bridge.last_update === null || timestamp(data.bridge.last_update)));
        requireValue(['healthy', 'degraded', 'unavailable', 'unknown'].includes(data.system.status));
        requireValue(object(data.intervention) && typeof data.intervention.guidance_text === 'string'
            && typeof data.intervention.intervention_type === 'string' && typeof data.intervention.parent_alert === 'boolean');
        if (data.emotion !== null) checkEmotion(data.emotion);
        if (data.behavior !== null) checkBehavior(data.behavior);
        if (data.data_available) requireValue(data.emotion !== null);
    } else if (name === 'analytics') {
        requireValue(data.days === state.historyDays && integer(data.total_records) && object(data.counts)
            && Array.isArray(data.series) && data.series.length <= 500);
        checkTrend(data.trend);
        Object.values(data.counts).forEach(count => requireValue(integer(count)));
        data.series.forEach(point => requireValue(object(point) && timestamp(point.timestamp) && number(point.valence, -1, 1)));
    } else if (name === 'history') {
        requireValue(data.days === state.historyDays && data.offset === state.historyOffset
            && data.limit === CONFIG.pageSize && integer(data.total) && typeof data.has_more === 'boolean'
            && Array.isArray(data.records) && data.records.length <= data.limit);
        data.records.forEach(record => requireValue(object(record) && timestamp(record.timestamp)
            && typeof record.category === 'string' && typeof record.cause === 'string'
            && number(record.valence, -1, 1) && number(record.arousal, 0, 1)));
    } else if (name === 'report') {
        requireValue(typeof data.data_available === 'boolean' && typeof data.summary === 'string'
            && typeof data.period_start === 'string' && typeof data.period_end === 'string'
            && strings(data.highlights) && strings(data.concerns) && strings(data.suggestions)
            && integer(data.interaction_count) && (data.health_score === null || number(data.health_score, 0, 100)));
        if (data.emotion_trend !== null) checkTrend(data.emotion_trend);
        if (!data.data_available) requireValue(data.health_score === null);
    } else if (name === 'system') {
        requireValue(timestamp(data.timestamp) && object(data.components) && strings(data.reasons)
            && ['healthy', 'degraded', 'unavailable'].includes(data.status));
        Object.keys(COMPONENT_LABELS).forEach(key => {
            const component = data.components[key];
            requireValue(object(component) && Object.hasOwn(STATUS_LABELS, component.status)
                && typeof component.reason === 'string' && (component.checked_at === null || timestamp(component.checked_at)));
        });
    } else if (name === 'settings') {
        requireValue(typeof data.local_only === 'boolean' && typeof data.single_profile === 'boolean'
        && typeof data.api_base === 'string' && typeof data.privacy_notice === 'string'
            && typeof data.app_env === 'string' && object(data.storage)
            && Object.hasOwn(STATUS_LABELS, data.storage.status) && integer(data.storage.retention_days)
            && typeof data.storage.raw_text_saved === 'boolean');
    }
}
function requestUrl(name) {
    const routes = {
        snapshot: '/dashboard/snapshot', system: '/system/status', settings: '/system/settings',
        analytics: '/emotions/analytics?days=' + state.historyDays,
        history: '/emotions/history?days=' + state.historyDays + '&limit=' + CONFIG.pageSize + '&offset=' + state.historyOffset,
        report: '/reports/parent?days=' + state.reportDays, export: '/reports/parent.md?days=' + state.reportDays,
    };
    return CONFIG.apiBase + routes[name];
}
function demoAvailable() { return window.SoulCompanionDemo && typeof window.SoulCompanionDemo.get === 'function'; }
async function requestResource(url, controller, format = 'json') {
    let timer, abortHandler, received = false, timedOut = false;
    const aborted = new Promise((_, reject) => {
        abortHandler = () => reject(new Error('Request cancelled'));
        controller.signal.addEventListener('abort', abortHandler, { once: true });
    });
    const deadline = new Promise((_, reject) => {
        timer = setTimeout(() => {
            timedOut = true; reject(new Error('Request deadline exceeded')); controller.abort();
        }, CONFIG.requestTimeout);
    });
    try {
        const response = fetch(url, { signal: controller.signal, credentials: 'same-origin' }).then(async res => {
            received = true;
            if (!res.ok) throw new Error('HTTP ' + res.status);
            if (format === 'blob') {
                requireValue((res.headers.get('content-type') || '').startsWith('text/markdown'));
                return res.blob();
            }
            return res.json();
        });
        return await Promise.race([response, deadline, aborted]);
    } catch (error) {
        error.connectionState = received && !timedOut ? 'ERROR' : 'OFFLINE';
        throw error;
    } finally {
        clearTimeout(timer); controller.signal.removeEventListener('abort', abortHandler);
    }
}
function renderConnectionState() {
    const live = channels.snapshot;
    const mode = live.error ? live.error : state.mode === 'demo' ? 'DEMO' : live.lastAt ? 'REAL' : 'CONNECTING';
    const messages = { CONNECTING: '正在连接后端…', DEMO: 'DEMO DATA · 合成演示数据', REAL: 'REAL · 后端已连接',
        OFFLINE: 'Backend disconnected · OFFLINE · 实时数据不可用', ERROR: 'ERROR · 实时数据更新失败' };
    let message = messages[mode];
    if (mode === 'REAL' && live.data && !live.data.data_available) message += ' · 暂无感知数据';
    text('connection-status', message); document.body.dataset.connection = mode.toLowerCase();
    const dot = $('system-status');
    if (dot) { dot.classList.toggle('offline', mode !== 'REAL'); dot.title = message; }
    if ($('demo-badge')) {
        $('demo-badge').hidden = state.mode !== 'demo';
        text('demo-badge', state.demoOnly ? 'DEMO DATA · 静态合成演示'
            : 'DEMO DATA · 合成视图（不会停止后台采集）');
    }
    text('footer-mode', state.mode === 'demo'
        ? state.demoOnly ? 'DEMO DATA · 静态合成演示，无后端' : 'DEMO DATA · 浏览器合成视图；后台采集由服务配置控制'
        : '本机单儿童产品 · REAL');
    if ($('api-doc-link')) $('api-doc-link').hidden = state.mode === 'demo';
    ['real', 'demo'].forEach(value => {
        if ($('mode-' + value)) $('mode-' + value).setAttribute('aria-pressed', String(state.mode === value));
    });
}
function markChannel(name, loading = false) {
    const channel = channels[name];
    let message = loading ? '正在更新…' : channel.lastAt ? '更新于 ' + formatTime(new Date(channel.lastAt).toISOString()) : '等待数据';
    if (channel.error) message = channel.error + ' · 更新失败；' + (channel.lastAt ? '以下为最后一次读取的旧数据' : '暂无可用数据');
    text(name + '-state', message);
    document.querySelectorAll('[data-channel="' + name + '"]').forEach(panel => {
        panel.dataset.stale = String(Boolean(channel.error)); panel.setAttribute('aria-busy', String(loading));
    });
    if (name === 'history') {
        if ($('history-prev')) $('history-prev').disabled = loading || state.historyOffset === 0;
        if ($('history-next')) $('history-next').disabled = loading || !channel.data || !channel.data.has_more;
    }
    if (name === 'export' && $('report-export')) $('report-export').disabled = loading;
    renderConnectionState();
}
async function refreshChannel(name, force = false) {
    const channel = channels[name];
    if (!force && (channel.inFlight || (channel.lastAt && !channel.interval) || Date.now() < channel.nextAt)) return null;
    if (channel.controller) channel.controller.abort();
    const generation = ++channel.generation, epoch = state.epoch, mode = state.mode;
    const controller = new AbortController();
    channel.controller = controller; channel.inFlight = true; channel.nextAt = Date.now() + channel.interval;
    markChannel(name, true);
    const current = () => epoch === state.epoch && generation === channel.generation;
    try {
        let data;
        if (mode === 'demo') {
            requireValue(demoAvailable());
            data = name === 'export' ? new Blob([demoReportMarkdown()], { type: 'text/markdown;charset=utf-8' })
                : window.SoulCompanionDemo.get(requestUrl(name));
        } else data = await requestResource(requestUrl(name), controller, name === 'export' ? 'blob' : 'json');
        if (!current()) return null;
        if (name !== 'export') checkResponse(name, data);
        channel.data = data; channel.error = null; channel.failures = 0; channel.lastAt = Date.now();
        if (name !== 'export') renderers[name](data);
        return data;
    } catch (error) {
        if (!current()) return null;
        channel.error = error.connectionState || 'ERROR'; channel.failures++;
        const base = channel.interval || 5000;
        channel.nextAt = Date.now() + Math.min(base * Math.pow(2, Math.min(channel.failures, 4)), Math.max(base, 30000));
        if (name === 'snapshot') renderRisk(null);
        if (!channel.data && name === 'report') text('parent-summary', '未能获取所选范围报告，请重试');
        if (!channel.data && name === 'analytics') text('chart-description', '未能获取所选范围趋势，请重试');
        if (!channel.data && name === 'history') text('history-summary', '未能获取所选范围历史，请重试');
        if (name === 'system' && channels.settings.data) renderSettings(channels.settings.data);
        return null;
    } finally {
        if (current()) { channel.inFlight = false; channel.controller = null; markChannel(name); }
    }
}
async function refreshAll(force = false) {
    return Promise.all(['snapshot', 'system', 'analytics', 'history', 'report', 'settings'].map(name => refreshChannel(name, force)));
}
function setMeter(id, value, max = 1) {
    const fill = $(id); if (!fill) return;
    fill.style.width = value === null ? '0%' : Math.max(0, Math.min(100, value / max * 100)) + '%';
    const meter = fill.parentElement;
    if (value === null) meter.removeAttribute('aria-valuenow');
    else meter.setAttribute('aria-valuenow', String(Math.max(0, Math.min(max, value))));
    meter.setAttribute('aria-valuetext', value === null ? '暂无数据' : String(value));
}
function renderEmotion(data) {
    const info = data ? emotionInfo(data.category) : { icon: '—', label: '暂无感知数据', color: '#555' };
    text('emotion-icon', info.icon); text('emotion-label', info.label);
    if ($('emotion-label')) $('emotion-label').style.color = info.color;
    [['confidence', 'confidence'], ['arousal', 'arousal']].forEach(([prefix, key]) => {
        setMeter(prefix + '-bar', data ? data[key] : null); text(prefix + '-value', data ? data[key].toFixed(2) : '--');
    });
    text('valence-value', data ? data.valence.toFixed(2) : '--');
    if ($('valence-indicator')) {
        $('valence-indicator').hidden = !data;
        $('valence-indicator').style.left = data ? ((data.valence + 1) / 2 * 100) + '%' : '50%';
    }
    text('vision-source', '👁️ 视觉: ' + (data ? emotionInfo(data.vision_emotion).label : '--'));
    text('speech-source', '🎤 语音: ' + (data ? emotionInfo(data.speech_emotion).label : '--'));
    text('env-source', '🌡️ 环境: ' + (data ? data.environment_signal : '--'));
    text('emotion-cause', data ? data.emotional_cause : '');
    text('attention-value', data ? Math.round(data.attention_level * 100) + '%' : '--');
}
function renderBehavior(data) {
    const actions = data ? data.actions.map(value => Object.hasOwn(ACTION_LABELS, value) ? ACTION_LABELS[value] : value) : [];
    renderTextItems($('behavior-actions'), actions, 'div', 'action-item', data ? '无动作' : '暂无行为数据');
    if ($('led-indicator')) {
        $('led-indicator').style.background = data && /^#[0-9a-f]{6}$/i.test(data.led_color) ? data.led_color : '#888';
        $('led-indicator').style.opacity = data ? data.led_brightness : 0.2;
    }
    text('led-info', data ? data.led_color + ' 亮度:' + Math.round(data.led_brightness * 100) + '%' : '--');
    setMeter('speech-rate-bar', data ? data.speech_rate : null, 1.5); setMeter('servo-speed-bar', data ? data.servo_speed : null);
    text('speech-rate-value', data ? data.speech_rate.toFixed(1) + 'x' : '--');
    text('servo-speed-value', data ? data.servo_speed.toFixed(1) : '--'); text('behavior-reason', data ? data.reason : '');
}
function renderRisk(risk) {
    let message = '风险状态未知：尚无有效检查结果', value = 'unknown';
    if (risk && risk.status === 'known' && fresh(risk.checked_at)) {
        value = risk.has_risk ? 'warning' : 'known';
        message = risk.has_risk ? '需要关注：' + (risk.triggers.join('；') || '检测到风险') : '最近一次检查未检测到风险信号';
        message += ' · 检查于 ' + formatTime(risk.checked_at);
    }
    text('risk-text', message);
    if ($('risk-alert')) { $('risk-alert').hidden = false; $('risk-alert').dataset.risk = value; }
}
function renderSnapshot(data) {
    const sourceFresh = data.data_available && data.emotion && fresh(data.bridge.last_update, 10000) && fresh(data.emotion.timestamp, 10000);
    renderEmotion(sourceFresh ? data.emotion : null); renderBehavior(sourceFresh ? data.behavior : null);
    text('source-time', data.data_available && !sourceFresh ? '感知数据已过期，等待新记录'
        : sourceFresh ? '感知时间：' + formatTime(data.bridge.last_update) : '感知来源未就绪');
    text('bridge-summary', data.bridge.connected ? '桥接' + (data.bridge.running ? '运行中' : '已停止')
        + ' · 周期 ' + data.bridge.cycle_count : '未连接设备桥接');
    text('intervention-guidance', sourceFresh ? data.intervention.guidance_text : '暂无实时干预建议');
    text('intervention-type', sourceFresh ? data.intervention.intervention_type : '--'); renderRisk(data.risk);
}
function renderDistribution(counts) {
    const container = $('emotion-distribution'); if (!container) return; container.replaceChildren();
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    if (!total) { container.appendChild(node('span', '暂无数据', 'dist-item')); return; }
    Object.entries(counts).sort((a, b) => b[1] - a[1]).forEach(([category, count]) => {
        const info = emotionInfo(category), item = node('div', undefined, 'dist-item'), dot = node('span', undefined, 'dist-dot');
        dot.style.background = info.color; dot.setAttribute('aria-hidden', 'true'); item.appendChild(dot);
        item.appendChild(node('span', info.icon + ' ' + info.label + ' ' + Math.round(count / total * 100) + '%'));
        container.appendChild(item);
    });
}
function renderAnalytics(data) {
    const trend = data.trend;
    text('trend-dominant', data.total_records ? emotionInfo(trend.dominant_emotion).label : '--');
    text('trend-valence', data.total_records ? trend.average_valence.toFixed(2) : '--');
    text('trend-stability', data.total_records ? Math.round(trend.stability_score * 100) + '%' : '--'); text('trend-count', data.total_records);
    renderDistribution(data.counts);
    text('chart-description', data.series.length < 2 ? '数据不足，暂无可绘制的趋势。历史表格提供记录明细。'
        : state.historyDays + '天内 ' + data.total_records + ' 条记录；图中展示 ' + data.series.length
            + ' 个采样点。时间：' + formatTime(data.series[0].timestamp) + ' 至 '
            + formatTime(data.series[data.series.length - 1].timestamp) + '。平均效价 ' + trend.average_valence.toFixed(2) + '。');
    drawValenceChart();
}
function drawValenceChart() {
    const canvas = $('valence-chart'); if (!canvas) return;
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    const rect = canvas.parentElement.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
    const width = Math.max(200, rect.width), height = Math.max(160, rect.height);
    canvas.width = width * ratio; canvas.height = height * ratio; ctx.scale(ratio, ratio); ctx.clearRect(0, 0, width, height);
    const points = channels.analytics.data ? channels.analytics.data.series : [];
    if (points.length < 2) { ctx.fillStyle = '#555'; ctx.font = '14px sans-serif'; ctx.fillText('暂无趋势数据', 24, 80); return; }
    const left = 40, top = 20, chartW = width - 60, chartH = height - 55;
    const start = milliseconds(points[0].timestamp), end = milliseconds(points[points.length - 1].timestamp), span = Math.max(1, end - start);
    ctx.strokeStyle = '#bbb'; ctx.beginPath(); ctx.moveTo(left, top + chartH / 2); ctx.lineTo(left + chartW, top + chartH / 2); ctx.stroke();
    ctx.strokeStyle = '#23752b'; ctx.lineWidth = 2; ctx.beginPath();
    points.forEach((point, index) => {
        const x = left + (milliseconds(point.timestamp) - start) / span * chartW, y = top + (1 - point.valence) / 2 * chartH;
        if (index) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    });
    ctx.stroke(); ctx.fillStyle = '#555'; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
    ctx.fillText('+1', left - 8, top + 4); ctx.fillText('0', left - 8, top + chartH / 2 + 4); ctx.fillText('-1', left - 8, top + chartH + 4);
    ctx.textAlign = 'left'; ctx.fillText(new Date(start).toLocaleDateString('zh-CN'), left, height - 8);
    ctx.textAlign = 'right'; ctx.fillText(new Date(end).toLocaleDateString('zh-CN'), left + chartW, height - 8);
}
function renderHistory(data) {
    const body = $('history-rows'); if (!body) return; body.replaceChildren();
    data.records.forEach(record => {
        const row = node('tr');
        [formatTime(record.timestamp), emotionInfo(record.category).label, record.valence.toFixed(2), record.arousal.toFixed(2), record.cause || '--']
            .forEach(value => row.appendChild(node('td', value)));
        body.appendChild(row);
    });
    if (!data.records.length) { const row = node('tr'), cell = node('td', '此时间范围暂无记录'); cell.colSpan = 5; row.appendChild(cell); body.appendChild(row); }
    text('history-summary', state.historyDays + '天 · 共 ' + data.total + ' 条；'
        + (data.records.length ? '第 ' + (data.offset + 1) + '–' + (data.offset + data.records.length) + ' 条' : '当前页为空'));
    text('history-timezone', '时间采用本机时区 ' + zoneLabel() + '；无时区的设备记录按本机时间解释。');
}
function renderReport(data) {
    const score = data.health_score, circumference = 2 * Math.PI * 52, ring = $('health-ring');
    if (ring) {
        ring.style.strokeDashoffset = circumference * (1 - (score === null ? 0 : score) / 100);
        ring.style.stroke = score === null ? '#777' : score >= 70 ? '#23752b' : score >= 40 ? '#a35e00' : '#aa2828';
    }
    text('health-score-text', score === null ? '暂无数据' : Math.round(score)); text('parent-summary', data.summary);
    text('report-period', data.period_start + ' 至 ' + data.period_end + ' · ' + data.interaction_count + ' 条记录');
    renderTextItems($('parent-highlights'), data.highlights, 'li', '', '暂无亮点记录');
    renderTextItems($('parent-concerns'), data.concerns, 'li', '', data.data_available ? '本报告未列出关注事项' : '暂无足够数据');
    renderTextItems($('parent-suggestions'), data.suggestions, 'li', '', '暂无建议');
}
function renderSystem(data) {
    const body = $('device-rows'); if (!body) return; body.replaceChildren();
    Object.entries(COMPONENT_LABELS).forEach(([key, label]) => {
        const component = data.components[key], row = node('tr'); row.dataset.status = component.status;
        [label, STATUS_LABELS[component.status] + ' (' + component.status + ')', component.reason, formatTime(component.checked_at)]
            .forEach(value => row.appendChild(node('td', value))); body.appendChild(row);
    });
    text('system-summary', STATUS_LABELS[data.status] + ' · ' + (data.reasons.join('；') || '检查已完成'));
    const settings = channels.settings.data;
    if (settings && settings.mode === data.mode) renderSettings(settings);
}
function displayedStorageStatus(data) {
    if (channels.system.error && data.mode === 'real') return 'unknown';
    const system = channels.system.data;
    if (system && system.mode === data.mode && fresh(system.timestamp)) return system.components.database.status;
    return data.storage.status;
}
function renderSettings(data) {
    text('setting-mode', data.mode === 'demo' ? 'DEMO DATA · 合成演示' : 'REAL · 真实数据');
    text('setting-scope', (data.local_only ? '仅本机访问' : '远程模式') + ' · ' + (data.single_profile ? '单儿童档案' : '多档案'));
    text('setting-api', state.demoOnly ? '静态演示，不连接后端' : data.api_base); text('setting-env', data.app_env);
    const browserDemo = data.mode === 'demo' && !state.demoOnly;
    text('setting-storage', browserDemo ? '当前合成视图不使用数据库；后台存储状态未确认'
        : STATUS_LABELS[displayedStorageStatus(data)] + (data.mode === 'demo' ? ' · 合成数据不持久化' : ' · SQLite 本地存储'));
    text('setting-retention', data.storage.retention_days ? data.storage.retention_days + ' 天，需手动清理' : '未启用自动清理');
    text('setting-raw', browserDemo ? '当前合成视图不保存原始文本；后台策略由服务配置决定'
        : data.storage.raw_text_saved ? '当前配置允许保存原始文本' : '不保存原始文本');
    text('privacy-notice', browserDemo
        ? '当前浏览器只展示合成数据。切换此视图不会停止后台摄像头、麦克风或记录；若需禁止后台采集，请以 SOULCOMPANION_DEMO_MODE=true 启动服务。'
        : data.privacy_notice);
}
const renderers = { snapshot: renderSnapshot, analytics: renderAnalytics, history: renderHistory,
    report: renderReport, system: renderSystem, settings: renderSettings };
function clearReport(message = '等待报告数据') {
    text('health-score-text', '--'); text('parent-summary', message); text('report-period', '');
    if ($('health-ring')) {
        $('health-ring').style.strokeDashoffset = 2 * Math.PI * 52;
        $('health-ring').style.stroke = '#777';
    }
    ['parent-highlights', 'parent-concerns', 'parent-suggestions']
        .forEach(id => renderTextItems($(id), [], 'li', '', '暂无所选范围数据'));
}
function clearAnalytics(message = '等待趋势数据') {
    ['trend-dominant', 'trend-valence', 'trend-stability', 'trend-count'].forEach(id => text(id, '--'));
    renderDistribution({}); text('chart-description', message); drawValenceChart();
}
function clearRenderedData() {
    renderEmotion(null); renderBehavior(null); renderRisk(null);
    ['history-rows', 'device-rows'].forEach(id => { if ($(id)) $(id).replaceChildren(); });
    ['source-time', 'bridge-summary', 'history-summary', 'system-summary', 'report-period', 'setting-mode', 'setting-scope',
        'setting-api', 'setting-env', 'setting-storage', 'setting-retention', 'setting-raw', 'privacy-notice'].forEach(id => text(id, '等待数据'));
    clearReport(); clearAnalytics();
    text('intervention-guidance', '暂无实时干预建议'); text('intervention-type', '--');
}
function parseUrlFlags() {
    state.demoOnly = document.body.dataset.demoOnly === 'true';
    const params = new URLSearchParams(window.location.search);
    state.mode = state.demoOnly || document.body.dataset.mode === 'demo' || params.get('demo') === '1' ? 'demo' : 'real';
    if (!state.demoOnly && params.get('nodemo') === '1') state.mode = 'real';
}
function setMode(mode) {
    if (!['real', 'demo'].includes(mode) || (state.demoOnly && mode === 'real')) return Promise.resolve(false);
    state.epoch++; state.mode = mode; state.historyOffset = 0;
    Object.values(channels).forEach(channel => {
        channel.generation++; if (channel.controller) channel.controller.abort();
        channel.controller = null; channel.inFlight = false; channel.data = null;
        channel.lastAt = 0; channel.nextAt = 0; channel.failures = 0; channel.error = null;
    });
    clearRenderedData(); renderConnectionState(); return refreshAll(true);
}
function setHistoryRange(days) {
    if (![1, 7, 30].includes(days)) return Promise.resolve();
    state.historyDays = days; state.historyOffset = 0;
    document.querySelectorAll('.range-btn').forEach(button => {
        const active = Number(button.dataset.days) === days;
        button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));
    });
    ['analytics', 'history'].forEach(name => {
        channels[name].data = null; channels[name].lastAt = 0; channels[name].error = null;
    });
    if ($('history-rows')) $('history-rows').replaceChildren();
    text('history-summary', '正在读取 ' + days + ' 天记录');
    clearAnalytics('正在读取 ' + days + ' 天趋势');
    return Promise.all([refreshChannel('analytics', true), refreshChannel('history', true)]);
}
function changeHistoryPage(direction) {
    const data = channels.history.data;
    if (!data || (direction > 0 && !data.has_more)) return Promise.resolve();
    state.historyOffset = Math.max(0, state.historyOffset + direction * CONFIG.pageSize);
    return refreshChannel('history', true);
}
function setReportRange(days) {
    if (![1, 7, 30].includes(days)) return Promise.resolve();
    if (days !== state.reportDays) {
        const channel = channels.export;
        channel.generation++;
        if (channel.controller) channel.controller.abort();
        channel.controller = null; channel.inFlight = false; channel.data = null;
        channel.lastAt = 0; channel.nextAt = 0; channel.error = null;
        markChannel('export');
        text('export-state', '报告范围已变化，请重新导出');
    }
    state.reportDays = days;
    channels.report.data = null; channels.report.lastAt = 0; channels.report.error = null;
    clearReport('正在生成 ' + days + ' 天报告');
    return refreshChannel('report', true);
}
function demoReportMarkdown() {
    requireValue(demoAvailable());
    const report = window.SoulCompanionDemo.get(requestUrl('report')); checkResponse('report', report);
    const blocks = ['# DEMO DATA · 合成演示家长报告', '', '所有内容为程序合成，不代表真实儿童数据。',
        '', '范围：' + report.period_start + ' 至 ' + report.period_end, '', report.summary];
    [['亮点', report.highlights], ['关注事项', report.concerns], ['建议', report.suggestions]].forEach(([title, values]) => {
        blocks.push('', '## ' + title, ''); values.forEach(value => blocks.push('- ' + value));
    });
    return blocks.join('\n') + '\n';
}
async function exportReport() {
    const epoch = state.epoch, mode = state.mode, days = state.reportDays;
    const data = await refreshChannel('export', true);
    if (!data || epoch !== state.epoch || mode !== state.mode || days !== state.reportDays) return false;
    const url = URL.createObjectURL(data);
    try {
        const link = node('a'); link.href = url; link.download = 'parent-report-' + mode + '-' + days + 'd.md';
        document.body.appendChild(link); link.click(); link.remove();
        text('export-state', state.mode === 'demo' ? '已导出 DEMO DATA 合成报告' : '已导出真实历史报告');
    } finally { setTimeout(() => URL.revokeObjectURL(url), 0); }
    return true;
}
function updateTime() { text('current-time', new Date().toLocaleString('zh-CN', { hour12: false }) + ' · ' + zoneLabel()); }
function schedule() {
    if (!document.hidden) { updateTime(); void refreshAll(); }
    state.timer = setTimeout(schedule, CONFIG.refreshInterval);
}
function start() {
    if (state.started) return;
    state.started = true; parseUrlFlags(); if ($('mode-real')) $('mode-real').disabled = state.demoOnly;
    [['mode-real', () => setMode('real')], ['mode-demo', () => setMode('demo')],
        ['retry-connection', () => refreshChannel('snapshot', true)], ['history-prev', () => changeHistoryPage(-1)],
        ['history-next', () => changeHistoryPage(1)],
        ['history-refresh', () => Promise.all([refreshChannel('analytics', true), refreshChannel('history', true)])],
        ['report-refresh', () => refreshChannel('report', true)], ['report-export', exportReport],
        ['system-refresh', () => refreshChannel('system', true)], ['settings-refresh', () => refreshChannel('settings', true)]]
        .forEach(([id, action]) => { if ($(id)) $(id).addEventListener('click', action); });
    document.querySelectorAll('.range-btn').forEach(button => button.addEventListener('click', () => setHistoryRange(Number(button.dataset.days))));
    if ($('report-range')) $('report-range').addEventListener('change', event => setReportRange(Number(event.target.value)));
    let resizeTimer;
    window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(drawValenceChart, 200); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void refreshAll(); });
    clearRenderedData(); renderConnectionState(); updateTime(); schedule();
}
window.SoulCompanionApp = { start, refreshAll, refreshChannel, setMode, setHistoryRange,
    changeHistoryPage, setReportRange, exportReport, channels, state, config: CONFIG };
document.addEventListener('DOMContentLoaded', start);
