#!/usr/bin/env node
/**
 * scripts/verify_demo.js - 演示引擎端到端自测（保留作回归）
 *
 * 在 Node 沙箱中加载 web/static/demo-data.js，逐项验证：
 *   1. /api/emotion/current 字段齐全
 *   2. 4 个面板依赖的每个 URL 都返回非 null 且结构正确
 *   3. valence-series 不同 days 长度不同
 *   4. counts 的键是合法情绪类别
 *   5. 连续采样时情绪在演化
 *   6. 两次 valence-series 结果相同（决定论，避免图表闪烁）
 *   7. 演示模式 actions 里的值都存在于 ACTION_LABELS
 *
 * 退出码：0 = 全部通过；1 = 存在失败或加载异常。
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const DEMO_PATH = path.join(ROOT, 'web', 'static', 'demo-data.js');

// 与 web/static/app.js 中的 ACTION_LABELS 键保持一致
const ACTION_LABELS = {
    heartbeat: 1, breathing_led: 1, ear_wiggle: 1, head_tilt: 1,
    soothing_voice: 1, excited_voice: 1, slow_motion: 1, still: 1,
    led_warm: 1, led_cool: 1, led_dim: 1
};

const VALID_CATEGORIES = [
    'happy', 'calm', 'anxious', 'sad', 'angry',
    'fearful', 'surprised', 'neutral', 'distressed'
];

// ─── 迷你测试框架 ─────────────────────────────────────────────────────
let passed = 0;
let failed = 0;

function check(name, cond, detail) {
    if (cond) {
        passed++;
        console.log('  \u2713 ' + name);
    } else {
        failed++;
        console.error('  \u2717 ' + name + (detail ? ('  \u2192 ' + detail) : ''));
    }
}

function isNum(v) { return typeof v === 'number' && isFinite(v); }
function isStr(v) { return typeof v === 'string'; }
function isArr(v) { return Array.isArray(v); }
function isObj(v) { return v !== null && typeof v === 'object'; }

// ─── 沙箱加载 demo-data.js ────────────────────────────────────────────
const code = fs.readFileSync(DEMO_PATH, 'utf8');
const sandbox = { console: console };
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox, { filename: 'demo-data.js' });

const demo = sandbox.window && sandbox.window.SoulCompanionDemo;

console.log('\n=== SoulCompanion 演示引擎自测 ===\n');

if (!demo || typeof demo.get !== 'function') {
    console.error('  \u2717 window.SoulCompanionDemo.get 未暴露');
    process.exit(1);
}

check('window.SoulCompanionDemo 已暴露且提供 get()', typeof demo.get === 'function');
check('isActive() 返回 true', demo.isActive() === true);

// ─── 1. /api/emotion/current 字段齐全 ─────────────────────────────────
console.log('\n[1] /api/emotion/current 字段齐全');
const current = demo.get('/api/emotion/current');
check('返回非 null', current !== null);
const REQUIRED_CURRENT_FIELDS = [
    'category', 'confidence', 'valence', 'arousal', 'vision_emotion',
    'speech_emotion', 'environment_signal', 'emotional_cause',
    'attention_level', 'timestamp'
];
REQUIRED_CURRENT_FIELDS.forEach(function (f) {
    check('字段存在: ' + f, current && Object.prototype.hasOwnProperty.call(current, f));
});
check('category 是合法情绪类别', VALID_CATEGORIES.indexOf(current.category) >= 0, current.category);
check('confidence 是数值', isNum(current.confidence));
check('valence ∈ [-1,1]', isNum(current.valence) && current.valence >= -1 && current.valence <= 1, String(current.valence));
check('arousal ∈ [0,1]', isNum(current.arousal) && current.arousal >= 0 && current.arousal <= 1, String(current.arousal));
check('attention_level ∈ [0,1]', isNum(current.attention_level) && current.attention_level >= 0 && current.attention_level <= 1, String(current.attention_level));
check('timestamp 是字符串', isStr(current.timestamp));

// ─── 2. 4 个面板依赖的每个 URL ────────────────────────────────────────
console.log('\n[2] 各面板依赖的 URL 结构');

// 2.1 behavior/command
const cmd = demo.get('/api/behavior/command');
check('behavior/command 非 null', cmd !== null);
check('  actions 是数组', cmd && isArr(cmd.actions));
check('  speech_rate 是数值', cmd && isNum(cmd.speech_rate));
check('  led_color 是字符串', cmd && isStr(cmd.led_color));
check('  led_brightness 是数值', cmd && isNum(cmd.led_brightness));
check('  servo_speed 是数值', cmd && isNum(cmd.servo_speed));
check('  priority 是数值', cmd && isNum(cmd.priority));
check('  reason 是字符串', cmd && isStr(cmd.reason));

// 2.2 behavior/status
const bstatus = demo.get('/api/behavior/status');
check('behavior/status 非 null 且结构正确', bstatus
    && typeof bstatus.hardware_available === 'boolean'
    && (bstatus.current_action === null || isStr(bstatus.current_action))
    && typeof bstatus.running === 'boolean');

// 2.3 emotion/trends
const trends = demo.get('/api/emotion/trends?period=daily');
check('emotion/trends 非 null 且结构正确', trends
    && isStr(trends.period)
    && VALID_CATEGORIES.indexOf(trends.dominant_emotion) >= 0
    && isNum(trends.average_valence)
    && isNum(trends.average_arousal)
    && isNum(trends.stability_score)
    && isArr(trends.risk_periods)
    && isArr(trends.positive_periods)
    && isNum(trends.total_records));

// 2.4 emotion/valence-series
const series = demo.get('/api/emotion/valence-series?days=1');
check('emotion/valence-series 非 null 且结构正确', series
    && isArr(series.series)
    && isNum(series.days)
    && (series.series.length === 0 || (isStr(series.series[0].timestamp) && isNum(series.series[0].valence))));

// 2.5 emotion/counts
const counts = demo.get('/api/emotion/counts?days=1');
check('emotion/counts 非 null 且结构正确', counts && isObj(counts.counts) && isNum(counts.days));

// 2.6 parent/report
const report = demo.get('/api/parent/report');
check('parent/report 非 null 且结构正确', report
    && isStr(report.period_start)
    && isStr(report.period_end)
    && isStr(report.summary)
    && (report.emotion_trend === null || isObj(report.emotion_trend))
    && isArr(report.highlights)
    && isArr(report.concerns)
    && isArr(report.suggestions)
    && isNum(report.interaction_count)
    && isNum(report.health_score));
check('  health_score ∈ [0,100]', report && report.health_score >= 0 && report.health_score <= 100);

// 2.7 risk/triggers
const risk = demo.get('/api/risk/triggers?window_minutes=60');
check('risk/triggers 非 null 且结构正确', risk
    && isArr(risk.triggers)
    && typeof risk.has_risk === 'boolean'
    && isNum(risk.window_minutes)
    && risk.window_minutes === 60);

// 2.8 system/status
const sys = demo.get('/api/system/status');
check('system/status 非 null 且结构正确', sys
    && isStr(sys.status)
    && isStr(sys.timestamp)
    && isObj(sys.bridge)
    && isObj(sys.modules)
    && isStr(sys.version));

// 2.9 bridge/status
const bridge = demo.get('/api/bridge/status');
check('bridge/status 非 null 且结构正确', bridge
    && typeof bridge.connected === 'boolean'
    && typeof bridge.is_running === 'boolean'
    && isNum(bridge.cycle_count)
    && isStr(bridge.last_update)
    && isNum(bridge.attention_level));

// 2.10 intervention/last
const plan = demo.get('/api/intervention/last');
check('intervention/last 非 null 且结构正确', plan
    && isStr(plan.intervention_type)
    && isStr(plan.guidance_text)
    && isStr(plan.guidance_style)
    && typeof plan.parent_alert === 'boolean'
    && isStr(plan.parent_note)
    && isNum(plan.duration_seconds)
    && isObj(plan.metadata));

// ─── 3. valence-series 不同 days 长度不同 ─────────────────────────────
console.log('\n[3] valence-series 不同 days 长度不同');
const s1 = demo.get('/api/emotion/valence-series?days=1').series.length;
const s7 = demo.get('/api/emotion/valence-series?days=7').series.length;
const s30 = demo.get('/api/emotion/valence-series?days=30').series.length;
check('days=1 < days=7 < days=30', s1 < s7 && s7 < s30, s1 + ' / ' + s7 + ' / ' + s30);
check('days=30 有 30 天数据可用', s30 > 0, String(s30));

// ─── 4. counts 的键是合法情绪类别 ─────────────────────────────────────
console.log('\n[4] counts 键合法性');
const counts7 = demo.get('/api/emotion/counts?days=7').counts;
const countKeys = Object.keys(counts7);
const badKeys = countKeys.filter(function (k) { return VALID_CATEGORIES.indexOf(k) < 0; });
check('所有 counts 键都是合法情绪类别', badKeys.length === 0, badKeys.join(','));
check('counts 非空', countKeys.length > 0);

// ─── 5. 情绪在演化（连续采样）────────────────────────────────────────
console.log('\n[5] 情绪在演化（连续采样）');
let evolved = false;
let used = 0;
let prev = demo.get('/api/emotion/current');
for (let i = 0; i < 25; i++) {
    used++;
    const next = demo.get('/api/emotion/current');
    if (JSON.stringify(next) !== JSON.stringify(prev)) { evolved = true; break; }
    prev = next;
}
check('连续采样中出现状态变化（在演化，非冻结）', evolved, '采样 ' + used + ' 次仍未变化');

// ─── 6. valence-series 决定论（两次结果相同）──────────────────────────
console.log('\n[6] valence-series 决定论');
const a = JSON.stringify(demo.get('/api/emotion/valence-series?days=7'));
const b = JSON.stringify(demo.get('/api/emotion/valence-series?days=7'));
check('两次 valence-series 结果完全相同（图表不闪烁）', a === b);

// ─── 7. actions 均存在于 ACTION_LABELS ────────────────────────────────
console.log('\n[7] actions ⊆ ACTION_LABELS');
const cmd2 = demo.get('/api/behavior/command');
const badActions = (cmd2.actions || []).filter(function (a) { return !ACTION_LABELS[a]; });
check('所有 actions 都存在于 ACTION_LABELS', badActions.length === 0, badActions.join(','));

// ─── 汇总 ─────────────────────────────────────────────────────────────
console.log('\n=== 结果：' + passed + ' passed, ' + failed + ' failed ===\n');
process.exit(failed === 0 ? 0 : 1);
