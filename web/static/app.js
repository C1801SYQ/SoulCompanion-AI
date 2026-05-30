/**
 * SoulCompanion AI - Dashboard JavaScript
 * Handles real-time data fetching, chart rendering, and UI updates.
 */

// ─── Configuration ───────────────────────────────────────────────────
const CONFIG = {
    refreshInterval: 1000,  // ms between data fetches
    chartPoints: 50,        // max points on valence chart
    apiBase: '',            // same origin
};

// ─── Emotion Mapping ─────────────────────────────────────────────────
const EMOTION_MAP = {
    happy:     { icon: '😊', label: '开心', color: '#FFD700' },
    calm:      { icon: '😌', label: '平静', color: '#87CEEB' },
    neutral:   { icon: '😐', label: '中性', color: '#4CAF50' },
    surprised: { icon: '😮', label: '惊讶', color: '#FF9800' },
    anxious:   { icon: '😰', label: '焦虑', color: '#FF9800' },
    sad:       { icon: '😢', label: '难过', color: '#7986CB' },
    angry:     { icon: '😠', label: '生气', color: '#EF5350' },
    fearful:   { icon: '😨', label: '害怕', color: '#B39DDB' },
    distressed:{ icon: '😵', label: '过载', color: '#FF5722' },
};

const ACTION_LABELS = {
    heartbeat:      '💓 心跳模拟',
    breathing_led:  '💡 呼吸灯',
    ear_wiggle:     '👂 耳朵摆动',
    head_tilt:      '🤔 好奇歪头',
    soothing_voice: '🗣️ 温柔语音',
    excited_voice:  '🗣️ 欢快语音',
    slow_motion:    '🦽 缓慢运动',
    still:          '🧊 静止模式',
    led_warm:       '💡 暖色灯',
    led_cool:       '💡 冷色灯',
    led_dim:        '💡 柔光灯',
};

// ─── State ───────────────────────────────────────────────────────────
let currentDays = 1;
let valenceData = [];

// ─── Fetch Helper ────────────────────────────────────────────────────
async function fetchJSON(url) {
    try {
        const res = await fetch(CONFIG.apiBase + url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (e) {
        console.error(`Fetch failed: ${url}`, e);
        return null;
    }
}

// ─── Emotion Panel ───────────────────────────────────────────────────
async function updateEmotionPanel() {
    const data = await fetchJSON('/api/emotion/current');
    if (!data) return;

    const emo = EMOTION_MAP[data.category] || EMOTION_MAP.neutral;

    // Badge
    document.getElementById('emotion-icon').textContent = emo.icon;
    const labelEl = document.getElementById('emotion-label');
    labelEl.textContent = emo.label;
    labelEl.style.color = emo.color;

    // Confidence bar
    const confPct = Math.round(data.confidence * 100);
    document.getElementById('confidence-bar').style.width = confPct + '%';
    document.getElementById('confidence-value').textContent = data.confidence.toFixed(2);

    // Valence indicator (-1 to 1 → 0% to 100%)
    const valPct = ((data.valence + 1) / 2) * 100;
    document.getElementById('valence-indicator').style.left = valPct + '%';
    document.getElementById('valence-value').textContent = data.valence.toFixed(2);

    // Arousal bar
    const aroPct = Math.round(data.arousal * 100);
    document.getElementById('arousal-bar').style.width = aroPct + '%';
    document.getElementById('arousal-value').textContent = data.arousal.toFixed(2);

    // Sources
    const vEmo = EMOTION_MAP[data.vision_emotion] || EMOTION_MAP.neutral;
    const sEmo = EMOTION_MAP[data.speech_emotion] || EMOTION_MAP.neutral;
    document.getElementById('vision-source').textContent = `👁️ 视觉: ${vEmo.label}`;
    document.getElementById('speech-source').textContent = `🎤 语音: ${sEmo.label}`;
    document.getElementById('env-source').textContent = `🌡️ 环境: ${data.environment_signal}`;

    // Cause
    const causeEl = document.getElementById('emotion-cause');
    causeEl.textContent = data.emotional_cause ? `💭 ${data.emotional_cause}` : '';

    // Refresh indicator
    document.getElementById('emotion-refresh').textContent = '●';
    setTimeout(() => {
        const el = document.getElementById('emotion-refresh');
        if (el) el.textContent = '';
    }, 500);
}

// ─── Behavior Panel ──────────────────────────────────────────────────
async function updateBehaviorPanel() {
    const data = await fetchJSON('/api/behavior/command');
    if (!data) return;

    // Actions
    const actionsEl = document.getElementById('behavior-actions');
    if (data.actions && data.actions.length > 0) {
        actionsEl.innerHTML = data.actions
            .map(a => `<div class="action-item">${ACTION_LABELS[a] || a}</div>`)
            .join('');
    } else {
        actionsEl.innerHTML = '<div class="action-item">无动作</div>';
    }

    // LED
    const ledEl = document.getElementById('led-indicator');
    ledEl.style.background = data.led_color || '#4CAF50';
    ledEl.style.opacity = data.led_brightness || 0.7;
    document.getElementById('led-info').textContent =
        `${data.led_color} 亮度:${Math.round((data.led_brightness || 0) * 100)}%`;

    // Speech rate
    const srPct = Math.round((data.speech_rate || 1.0) / 1.5 * 100);
    document.getElementById('speech-rate-bar').style.width = srPct + '%';
    document.getElementById('speech-rate-value').textContent = `${(data.speech_rate || 1.0).toFixed(1)}x`;

    // Servo speed
    const ssPct = Math.round((data.servo_speed || 0.5) * 100);
    document.getElementById('servo-speed-bar').style.width = ssPct + '%';
    document.getElementById('servo-speed-value').textContent = (data.servo_speed || 0.5).toFixed(1);

    // Reason
    document.getElementById('behavior-reason').textContent = data.reason || '';
}

// ─── Timeline Panel ──────────────────────────────────────────────────
async function updateTimelinePanel() {
    // Fetch trend data
    const trendData = await fetchJSON(`/api/emotion/trends?period=daily`);
    if (trendData) {
        const domEmo = EMOTION_MAP[trendData.dominant_emotion] || EMOTION_MAP.neutral;
        document.getElementById('trend-dominant').textContent = domEmo.label;
        document.getElementById('trend-dominant').style.color = domEmo.color;
        document.getElementById('trend-valence').textContent = trendData.average_valence.toFixed(2);
        document.getElementById('trend-stability').textContent =
            Math.round(trendData.stability_score * 100) + '%';
        document.getElementById('trend-count').textContent = trendData.total_records;
    }

    // Fetch valence series
    const seriesData = await fetchJSON(`/api/emotion/valence-series?days=${currentDays}`);
    if (seriesData && seriesData.series) {
        valenceData = seriesData.series;
        drawValenceChart();
    }

    // Fetch emotion counts for distribution
    const countsData = await fetchJSON(`/api/emotion/counts?days=${currentDays}`);
    if (countsData && countsData.counts) {
        renderDistribution(countsData.counts);
    }
}

// ─── Simple Canvas Chart ─────────────────────────────────────────────
function drawValenceChart() {
    const canvas = document.getElementById('valence-chart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * 2;   // HiDPI
    canvas.height = rect.height * 2;
    ctx.scale(2, 2);

    const w = rect.width;
    const h = rect.height;
    const padding = { top: 20, right: 20, bottom: 30, left: 40 };

    // Clear
    ctx.clearRect(0, 0, w, h);

    if (valenceData.length < 2) {
        ctx.fillStyle = '#999';
        ctx.font = '14px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('数据不足，请等待更多交互记录', w / 2, h / 2);
        return;
    }

    const data = valenceData.slice(-CONFIG.chartPoints);
    const chartW = w - padding.left - padding.right;
    const chartH = h - padding.top - padding.bottom;

    // Zero line
    const zeroY = padding.top + chartH / 2;
    ctx.strokeStyle = '#e0e0e0';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(padding.left, zeroY);
    ctx.lineTo(w - padding.right, zeroY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw valence line
    ctx.strokeStyle = '#4CAF50';
    ctx.lineWidth = 2;
    ctx.beginPath();

    data.forEach((d, i) => {
        const x = padding.left + (i / (data.length - 1)) * chartW;
        // valence: -1 to 1 → bottom to top
        const y = padding.top + ((1 - d.valence) / 2) * chartH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Fill area under curve
    ctx.lineTo(padding.left + chartW, zeroY);
    ctx.lineTo(padding.left, zeroY);
    ctx.closePath();
    ctx.fillStyle = 'rgba(76, 175, 80, 0.1)';
    ctx.fill();

    // Y-axis labels
    ctx.fillStyle = '#999';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText('+1', padding.left - 8, padding.top + 4);
    ctx.fillText('0', padding.left - 8, zeroY + 4);
    ctx.fillText('-1', padding.left - 8, padding.top + chartH + 4);
}

function renderDistribution(counts) {
    const container = document.getElementById('emotion-distribution');
    if (!container) return;

    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    if (total === 0) {
        container.innerHTML = '<span class="dist-item">暂无数据</span>';
        return;
    }

    container.innerHTML = Object.entries(counts)
        .sort((a, b) => b[1] - a[1])
        .map(([cat, count]) => {
            const emo = EMOTION_MAP[cat] || EMOTION_MAP.neutral;
            const pct = Math.round((count / total) * 100);
            return `<div class="dist-item">
                <span class="dist-dot" style="background:${emo.color}"></span>
                ${emo.icon} ${emo.label} ${pct}%
            </div>`;
        })
        .join('');
}

// ─── Parent Insight Panel ────────────────────────────────────────────
async function updateParentPanel() {
    const data = await fetchJSON('/api/parent/report');
    if (!data) return;

    // Health score ring
    const score = data.health_score || 0;
    const circumference = 2 * Math.PI * 52; // r=52
    const offset = circumference * (1 - score / 100);
    const ring = document.getElementById('health-ring');
    if (ring) {
        ring.style.strokeDashoffset = offset;
        // Color based on score
        if (score >= 70) ring.style.stroke = '#66BB6A';
        else if (score >= 40) ring.style.stroke = '#FFB74D';
        else ring.style.stroke = '#EF5350';
    }
    document.getElementById('health-score-text').textContent = Math.round(score);

    // Summary
    document.getElementById('parent-summary').textContent = data.summary || '暂无数据';

    // Highlights
    const hlEl = document.getElementById('parent-highlights');
    hlEl.innerHTML = (data.highlights && data.highlights.length > 0)
        ? data.highlights.map(h => `<li>${h}</li>`).join('')
        : '<li>暂无亮点记录</li>';

    // Concerns
    const conEl = document.getElementById('parent-concerns');
    conEl.innerHTML = (data.concerns && data.concerns.length > 0)
        ? data.concerns.map(c => `<li>${c}</li>`).join('')
        : '<li>无需特别关注</li>';

    // Suggestions
    const sugEl = document.getElementById('parent-suggestions');
    sugEl.innerHTML = (data.suggestions && data.suggestions.length > 0)
        ? data.suggestions.map(s => `<li>${s}</li>`).join('')
        : '<li>保持当前互动方式即可</li>';

    // Risk alert
    const riskData = await fetchJSON('/api/risk/triggers?window_minutes=60');
    const riskEl = document.getElementById('risk-alert');
    if (riskData && riskData.has_risk && riskData.triggers.length > 0) {
        riskEl.style.display = 'flex';
        document.getElementById('risk-text').textContent = riskData.triggers[0];
    } else {
        riskEl.style.display = 'none';
    }
}

// ─── System Status ───────────────────────────────────────────────────
async function updateSystemStatus() {
    const data = await fetchJSON('/api/system/status');
    const dot = document.getElementById('system-status');
    if (data && (data.status === 'running' || data.status === 'standalone')) {
        dot.classList.remove('offline');
        // Update title with bridge status
        if (data.bridge && data.bridge.connected) {
            dot.title = '桥接模式 - 实时数据';
        } else {
            dot.title = '独立模式 - 演示数据';
        }
    } else {
        dot.classList.add('offline');
    }
}

// ─── Time Display ────────────────────────────────────────────────────
function updateTime() {
    const now = new Date();
    const timeStr = now.toLocaleString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
    document.getElementById('current-time').textContent = timeStr;
}

// ─── Time Range Selector ─────────────────────────────────────────────
function initTimeRangeSelector() {
    document.querySelectorAll('.range-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentDays = parseInt(btn.dataset.days, 10);
            updateTimelinePanel();
        });
    });
}

// ─── Chart Resize ────────────────────────────────────────────────────
function initResizeHandler() {
    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(drawValenceChart, 200);
    });
}

// ─── Main Loop ───────────────────────────────────────────────────────
async function refreshAll() {
    await Promise.all([
        updateEmotionPanel(),
        updateBehaviorPanel(),
        updateParentPanel(),
        updateSystemStatus(),
    ]);
    await updateTimelinePanel();
}

// ─── Init ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initTimeRangeSelector();
    initResizeHandler();
    updateTime();

    // Initial fetch
    refreshAll();

    // Periodic refresh
    setInterval(refreshAll, CONFIG.refreshInterval);
    setInterval(updateTime, 1000);
});
