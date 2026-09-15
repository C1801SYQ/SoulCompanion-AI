/**
 * SoulCompanion AI - 纯前端演示数据引擎 (demo-data.js)
 * =====================================================
 * 目标：在没有 FastAPI 后端时（例如部署到 Cloudflare Pages 静态托管），
 * 让看板依然能展示"自洽、有真实感"的数据，而不会是一片空白。
 *
 * 设计原则：
 *  1. 零依赖：不引用任何外部库 / CDN，仅用标准 ECMAScript。
 *  2. 忠实复刻真实管线：模拟三模态输入（视觉表情 / 语音情绪+文本 /
 *     环境 bio_anxiety+hour），并走与 emotion/fusion_engine.py 完全一致的
 *     融合逻辑（缺失模态权重置零并归一化、一致度加成、单模态降权 0.75、
 *     注意力惩罚、白天只有 hour 时不投票、视觉 anxious/fearful 优先采信），
 *     产出与 /api/emotion/current 完全同构的 EmotionState 快照。
 *  3. 缓慢演化：情绪用随机游走 + 偶发事件（注意力流失 / 短暂焦虑 / 偶发过载），
 *     不会每帧乱跳。
 *  4. 决定论历史：预生成 30 天合成历史，使用固定种子的伪随机数，
 *     刷新页面后趋势图稳定、不闪烁。
 *  5. 接口对齐：get(url) 返回结构与 web/api.py 逐字段一致。
 *
 * 对外接口：
 *   window.SoulCompanionDemo = { get(url), isActive() }
 *
 * ⚠️ 免责声明：本文件产出的一切数据均为**合成演示数据**，
 *     不代表任何真实儿童。看板在使用演示数据时必须显示醒目徽章。
 */
(function (global) {
    'use strict';

    // ─────────────────────────────────────────────────────────────────
    // 常量（镜像 emotion/models.py 与 emotion/fusion_engine.py）
    // ─────────────────────────────────────────────────────────────────

    /** 情绪类别（与 EmotionCategory 枚举值一致）。 */
    var CATEGORIES = [
        'happy', 'calm', 'anxious', 'sad', 'angry',
        'fearful', 'surprised', 'neutral', 'distressed'
    ];

    /** 各情绪的效价预设（镜像 EMOTION_VALENCE）。 */
    var EMOTION_VALENCE = {
        happy: 0.8, calm: 0.3, surprised: 0.2, neutral: 0.0,
        anxious: -0.4, sad: -0.7, angry: -0.6,
        fearful: -0.8, distressed: -0.9
    };

    /** 各情绪的唤醒度预设（镜像 EMOTION_AROUSAL）。 */
    var EMOTION_AROUSAL = {
        happy: 0.7, calm: 0.2, surprised: 0.9, neutral: 0.3,
        anxious: 0.7, sad: 0.3, angry: 0.8,
        fearful: 0.9, distressed: 1.0
    };

    /** 视觉原始标签 → 情绪类别（镜像 VISION_EMOTION_MAP，含 disgust→anxious 现状）。 */
    var VISION_EMOTION_MAP = {
        happy: 'happy', surprise: 'surprised', sad: 'sad',
        anxious: 'anxious', angry: 'angry', fear: 'fearful',
        disgust: 'anxious', neutral: 'neutral'
    };

    /** 语音原始标签 → 情绪类别（镜像 SPEECH_EMOTION_MAP）。 */
    var SPEECH_EMOTION_MAP = {
        happy: 'happy', sad: 'sad', anxious: 'anxious',
        angry: 'angry', neutral: 'neutral'
    };

    /** 融合权重（镜像 FusionEngine.weights）。 */
    var WEIGHTS = { vision: 0.4, speech: 0.4, environment: 0.2 };

    /** 低注意力阈值（镜像 emotion.models.ATTENTION_THRESHOLD_LOW）。 */
    var ATTENTION_THRESHOLD_LOW = 0.3;

    /** 注意力临界阈值（镜像 intervention.ATTENTION_THRESHOLD_CRITICAL）。 */
    var ATTENTION_THRESHOLD_CRITICAL = 0.1;

    /** ASD 视觉优先类别（镜像 fusion_engine.ASD_VISION_PRIORITY）。 */
    var ASD_VISION_PRIORITY = ['anxious', 'fearful'];

    /** 紧急度集合（镜像 intervention.URGENT_URGENCIES）。 */
    var URGENT_URGENCIES = ['high'];

    /** 冷却窗口秒数（镜像干预引擎默认值）。 */
    var COOLDOWN_SECONDS = 30;
    var URGENT_COOLDOWN_SECONDS = 8;

    // ─────────────────────────────────────────────────────────────────
    // 情绪 → 行为映射（逐行照抄 emotion/behavior_sync.py）
    // ─────────────────────────────────────────────────────────────────

    var EMOTION_BEHAVIOR_MAP = {
        happy: {
            actions: ['ear_wiggle', 'led_warm', 'excited_voice'],
            speech_rate: 1.2, led_color: '#FFD700', led_brightness: 0.8, servo_speed: 0.7
        },
        calm: {
            actions: ['breathing_led', 'soothing_voice'],
            speech_rate: 0.9, led_color: '#87CEEB', led_brightness: 0.5, servo_speed: 0.3
        },
        neutral: {
            actions: ['breathing_led'],
            speech_rate: 1.0, led_color: '#4CAF50', led_brightness: 0.6, servo_speed: 0.5
        },
        surprised: {
            actions: ['head_tilt', 'ear_wiggle', 'led_warm'],
            speech_rate: 1.1, led_color: '#FF9800', led_brightness: 0.9, servo_speed: 0.8
        },
        anxious: {
            actions: ['heartbeat', 'breathing_led', 'soothing_voice', 'led_cool'],
            speech_rate: 0.7, led_color: '#64B5F6', led_brightness: 0.4, servo_speed: 0.2
        },
        sad: {
            actions: ['heartbeat', 'soothing_voice', 'slow_motion', 'led_cool'],
            speech_rate: 0.7, led_color: '#7986CB', led_brightness: 0.3, servo_speed: 0.2
        },
        angry: {
            actions: ['still', 'led_dim', 'soothing_voice'],
            speech_rate: 0.6, led_color: '#B0BEC5', led_brightness: 0.2, servo_speed: 0.1
        },
        fearful: {
            actions: ['heartbeat', 'still', 'soothing_voice', 'led_dim'],
            speech_rate: 0.6, led_color: '#B39DDB', led_brightness: 0.2, servo_speed: 0.1
        },
        distressed: {
            actions: ['still', 'led_dim', 'soothing_voice'],
            speech_rate: 0.5, led_color: '#E0E0E0', led_brightness: 0.1, servo_speed: 0.0
        }
    };

    var LOW_ATTENTION_BEHAVIORS = {
        actions: ['head_tilt', 'ear_wiggle'],
        led_color: '#FFEB3B',
        led_brightness: 0.7
    };

    // ─────────────────────────────────────────────────────────────────
    // 引导语模板（镜像 intervention.GUIDED_RESPONSES 的精简子集）
    // ─────────────────────────────────────────────────────────────────

    var GUIDED_RESPONSES = {
        happy: ['你今天看起来好开心呀！能告诉小予是什么让你这么高兴吗？', '哇，你的笑容好温暖！小予也很开心呢。'],
        calm: ['你今天很安静呢，小予陪着你哦。', '我们一起来做深呼吸好不好？吸——呼——'],
        neutral: ['小予在这里呢，你想聊点什么吗？', '我们一起来看看这个有趣的东西吧。'],
        surprised: ['哇，你发现了什么有趣的东西呀？', '你的眼睛亮起来了！能告诉小予吗？'],
        anxious: ['小予感觉到你有点紧张，没关系的，小予陪着你。', '我们一起来做深呼吸好吗？吸气——慢慢呼气——'],
        sad: ['你看起来有点难过，小予想陪着你。', '你可以告诉小予发生了什么，小予会听你说。'],
        angry: ['你看起来有点生气，小予理解你的感受。', '我们可以一起做深呼吸，让心情慢慢平静下来。'],
        fearful: ['小予在这里，你不用害怕。', '你可以抓住小予的手，小予会保护你。'],
        distressed: ['小予在这里陪着你，你不是一个人。', '我们慢慢来，不着急，小予会一直在这里。']
    };

    /** 模拟"孩子说的话"（用于语音通道的 text 与情绪推断）。 */
    var SPEECH_POOL = {
        happy: ['我今天玩了积木！', '这个真好玩！', '我好开心呀！'],
        calm: ['嗯……', '我在看那个。', '好的。'],
        neutral: ['小予你在吗？', '这是什么呀？', '我想喝水。'],
        anxious: ['这个声音好吵……', '我不想待在这里。', '有点吵，我害怕。'],
        sad: ['我不太想玩……', '我想妈妈了。'],
        angry: ['我不要！', '别碰我的东西！'],
        fearful: ['那个太响了……', '我害怕。'],
        distressed: ['太吵了……太吵了……', '我不要……不要……']
    };

    // ─────────────────────────────────────────────────────────────────
    // 基础工具函数
    // ─────────────────────────────────────────────────────────────────

    function clamp(v, lo, hi) {
        return v < lo ? lo : (v > hi ? hi : v);
    }

    function round(v, n) {
        var f = Math.pow(10, n);
        return Math.round(v * f) / f;
    }

    function average(arr) {
        if (!arr.length) return 0;
        var s = 0;
        for (var i = 0; i < arr.length; i++) s += arr[i];
        return s / arr.length;
    }

    function pick(arr, rng) {
        return arr[Math.floor(rng() * arr.length)];
    }

    /** mulberry32：可播种的确定性伪随机数发生器。 */
    function mulberry32(seed) {
        var a = seed >>> 0;
        return function () {
            a = (a + 0x6D2B79F5) | 0;
            var t = Math.imul(a ^ (a >>> 15), 1 | a);
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }

    /** 本地时间 → "YYYY-MM-DDTHH:MM:SS"（与 memory_axis 存储格式一致）。 */
    function localIso(ms) {
        var d = new Date(ms);
        function p(n) { return String(n).length < 2 ? '0' + n : String(n); }
        return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
            'T' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
    }

    /** 本地时间 → "YYYY-MM-DD"。 */
    function localDate(ms) {
        return localIso(ms).slice(0, 10);
    }

    // ─────────────────────────────────────────────────────────────────
    // 融合逻辑（镜像 emotion/fusion_engine.py）
    // ─────────────────────────────────────────────────────────────────

    function has(obj, key) {
        return Object.prototype.hasOwnProperty.call(obj, key);
    }

    /** 视觉通道解析：无人脸 / 无情绪 → null（缺失，不投票）。 */
    function parseVision(vState) {
        if (!vState) return null;
        if (vState.face_detected === false) return null;
        var raw = vState.emotion;
        if (!raw) return null;
        return has(VISION_EMOTION_MAP, raw) ? VISION_EMOTION_MAP[raw] : 'neutral';
    }

    /** 语音通道解析：无输入 / 无情绪 → null（缺失）。 */
    function parseSpeech(sState) {
        if (!sState) return null;
        var raw = sState.emotion;
        if (!raw) return null;
        return has(SPEECH_EMOTION_MAP, raw) ? SPEECH_EMOTION_MAP[raw] : 'neutral';
    }

    /**
     * 环境通道解析（镜像 R12 修复后的 _parse_environment）：
     *   1) 三读数为空 → None；
     *   2) 真实传感器优先：bio_anxiety>0.8→distressed，>0.6→anxious；noise>0.8→anxious；
     *   3) 存在真实读数（含 0.0）→ neutral；
     *   4) 只有 hour：夜间→calm，白天→null（不投票）。
     */
    function parseEnvironment(env) {
        if (!env) return null;

        var bio = has(env, 'bio_anxiety') ? env.bio_anxiety : undefined;
        var noise = has(env, 'noise_level') ? env.noise_level : undefined;
        var hour = has(env, 'hour') ? env.hour : undefined;

        function missing(v) { return v === undefined || v === null; }

        if (missing(bio) && missing(noise) && missing(hour)) return null;

        if (!missing(bio)) {
            if (bio > 0.8) return 'distressed';
            if (bio > 0.6) return 'anxious';
        }

        if (!missing(noise) && noise > 0.8) return 'anxious';

        if (!missing(bio) || !missing(noise)) return 'neutral';

        if (!missing(hour) && (hour >= 21 || hour <= 6)) return 'calm';

        return null;
    }

    /** 注意力计算（镜像 _calc_attention）：视觉不可用→0.5；人脸丢失→线性衰减。 */
    function calcAttention(vState) {
        if (!vState || !has(vState, 'face_detected')) return 0.5;

        if (!vState.face_detected) {
            var loss = has(vState, 'attention_loss_time') ? vState.attention_loss_time : 0.0;
            return Math.max(0.0, 1.0 - (loss / 10.0));
        }

        return 1.0;
    }

    /**
     * 加权融合（镜像 _weighted_fuse）：缺失模态置零并归一化、
     * 一致度加成、单模态降权 0.75、注意力惩罚、ASD 视觉优先采信。
     */
    function weightedFuse(vEmo, sEmo, eEmo, attention) {
        var modalities = [
            ['vision', vEmo],
            ['speech', sEmo],
            ['environment', eEmo]
        ];

        var present = [];
        for (var i = 0; i < modalities.length; i++) {
            var key = modalities[i][0];
            var emo = modalities[i][1];
            if (emo !== null && emo !== undefined) {
                present.push([emo, has(WEIGHTS, key) ? WEIGHTS[key] : 0.0]);
            }
        }

        var total = 0;
        for (var p = 0; p < present.length; p++) total += present[p][1];

        if (present.length === 0 || total <= 0) {
            return { category: 'neutral', confidence: 0.3, weights: {} };
        }

        // 各情绪类别加权得分
        var scores = {};
        var order = [];
        for (var q = 0; q < present.length; q++) {
            var e1 = present[q][0], w1 = present[q][1];
            if (!has(scores, e1)) { scores[e1] = 0.0; order.push(e1); }
            scores[e1] += w1;
        }

        // 得分最高者胜出（并列时保持插入顺序 → 视觉优先）
        var dominant = order[0];
        var best = 0;
        for (var o = 0; o < order.length; o++) {
            var cat = order[o];
            if (scores[cat] > best) { best = scores[cat]; dominant = cat; }
        }

        var rawConfidence = scores[dominant] / total;

        // 一致度加成：多个模态指向同一情绪时更可信
        var agreementCount = 0;
        for (var a = 0; a < present.length; a++) if (present[a][0] === dominant) agreementCount++;
        var agreementBonus = (agreementCount - 1) * 0.15;

        // 证据数量校正：仅 1 个模态天然证据不足
        var evidenceFactor = 1.0;
        if (present.length === 1) evidenceFactor = 0.75;
        else if (present.length === 2) evidenceFactor = 0.90;

        // 注意力惩罚：孩子没在看，读数可信度下降
        var attentionPenalty = (1.0 - attention) * 0.2;

        var confidence = rawConfidence * evidenceFactor + agreementBonus - attentionPenalty;
        confidence = clamp(confidence, 0.0, 1.0);

        // ASD 安全规则：视觉焦虑/恐惧优先采信
        if (vEmo !== null && ASD_VISION_PRIORITY.indexOf(vEmo) >= 0) {
            if (confidence < 0.6) {
                dominant = vEmo;
                confidence = Math.max(confidence, 0.6);
            }
        }

        var weights = {};
        for (var m = 0; m < modalities.length; m++) {
            var mk = modalities[m][0], me = modalities[m][1];
            if (me !== null && me !== undefined) {
                weights[mk] = (has(WEIGHTS, mk) ? WEIGHTS[mk] : 0.0) / total;
            }
        }

        return { category: dominant, confidence: confidence, weights: weights };
    }

    function label(emo) {
        return (emo === null || emo === undefined) ? 'unknown' : emo;
    }

    /** 原因推断（镜像 _infer_cause）。 */
    function inferCause(fused, vEmo, sEmo, eEmo, speechState) {
        if (fused === 'neutral') return '';

        var causes = [];

        if (vEmo === fused) causes.push('面部表情显示');

        var text = (speechState && speechState.text) ? speechState.text : '';
        if (sEmo === fused && text) causes.push('语音语调分析');

        if (eEmo === 'anxious' || eEmo === 'distressed') causes.push('环境压力信号');

        if (fused === 'anxious' || fused === 'sad') causes.push('可能需要关注');

        if (causes.length === 0) return '多模态信号综合判断';

        return causes.slice(0, 2).join(' + ');
    }

    /** 完整融合：三模态原始输入 → EmotionState 字段集合。 */
    function fuse(visionState, speechState, envSignals) {
        visionState = visionState || {};
        speechState = speechState || {};
        envSignals = envSignals || {};

        var vEmo = parseVision(visionState);
        var sEmo = parseSpeech(speechState);
        var eEmo = parseEnvironment(envSignals);

        var attention = calcAttention(visionState);
        var result = weightedFuse(vEmo, sEmo, eEmo, attention);
        var category = result.category;

        var valence = has(EMOTION_VALENCE, category) ? EMOTION_VALENCE[category] : 0.0;
        var arousal = has(EMOTION_AROUSAL, category) ? EMOTION_AROUSAL[category] : 0.5;
        var cause = inferCause(category, vEmo, sEmo, eEmo, speechState);

        return {
            category: category,
            confidence: round(result.confidence, 3),
            valence: round(valence, 3),
            arousal: round(arousal, 3),
            vision_emotion: label(vEmo),
            speech_emotion: label(sEmo),
            environment_signal: label(eEmo),
            emotional_cause: cause,
            attention_level: round(attention, 3),
            timestamp: localIso(Date.now()),
            source_weights: result.weights
        };
    }

    // ─────────────────────────────────────────────────────────────────
    // 行为 / 干预（镜像 behavior_sync.sync + intervention.evaluate 路由）
    // ─────────────────────────────────────────────────────────────────

    function buildReason(category, state) {
        var parts = ['情绪=' + category];
        if (state.attention_level < ATTENTION_THRESHOLD_LOW) parts.push('注意力低');
        if (state.arousal > 0.8) parts.push('高唤醒');
        if (state.confidence < 0.4) parts.push('低置信度');
        return parts.join(', ');
    }

    /** 生成 BehaviorCommand（与 /api/behavior/command 同构）。 */
    function buildBehavior(state) {
        var base = has(EMOTION_BEHAVIOR_MAP, state.category)
            ? EMOTION_BEHAVIOR_MAP[state.category]
            : EMOTION_BEHAVIOR_MAP.neutral;

        var actions = base.actions.slice();
        var speechRate = base.speech_rate;
        var ledColor = base.led_color;
        var ledBrightness = base.led_brightness;
        var servo = base.servo_speed;

        // 2. 注意力调整
        if (state.attention_level < ATTENTION_THRESHOLD_LOW) {
            for (var i = 0; i < LOW_ATTENTION_BEHAVIORS.actions.length; i++) {
                var act = LOW_ATTENTION_BEHAVIORS.actions[i];
                if (actions.indexOf(act) < 0) actions.push(act);
            }
            ledColor = LOW_ATTENTION_BEHAVIORS.led_color;
            ledBrightness = LOW_ATTENTION_BEHAVIORS.led_brightness;
        }

        // 3. 唤醒度调整
        if (state.arousal > 0.8) {
            ledBrightness = Math.max(0.1, ledBrightness - 0.2);
            servo = Math.max(0.0, servo - 0.2);
        } else if (state.arousal < 0.2) {
            ledBrightness = Math.min(0.8, ledBrightness + 0.1);
        }

        // 4. 置信度兜底
        if (state.confidence < 0.4) {
            if (actions.indexOf('soothing_voice') < 0) actions.push('soothing_voice');
            speechRate = Math.min(speechRate, 0.8);
        }

        // 5. 优先级
        var priority = (state.category === 'distressed' || state.category === 'fearful') ? 1 : 0;

        return {
            actions: actions,
            speech_rate: round(speechRate, 2),
            led_color: ledColor,
            led_brightness: round(ledBrightness, 2),
            servo_speed: round(servo, 2),
            priority: priority,
            reason: buildReason(state.category, state)
        };
    }

    function guidedResponse(category) {
        var pool = has(GUIDED_RESPONSES, category) ? GUIDED_RESPONSES[category] : GUIDED_RESPONSES.neutral;
        return pool[Math.floor(Math.random() * pool.length)];
    }

    /** 生成干预计划（与 /api/intervention/last 同构，路由镜像 _evaluate_intervention）。 */
    function buildIntervention(state) {
        var cat = state.category;
        var attention = state.attention_level;

        function plan(type, text, style, alert, note, duration, urgency, reason) {
            return {
                intervention_type: type,
                guidance_text: text,
                guidance_style: style,
                parent_alert: alert,
                parent_note: note,
                duration_seconds: duration,
                metadata: { urgency: urgency, reason: reason }
            };
        }

        if (cat === 'distressed') {
            return plan('calming_activity', guidedResponse(cat), 'calm', true,
                '孩子出现过载状态，建议减少环境刺激', 120, 'high', 'distressed');
        }
        if (cat === 'fearful') {
            return plan('breathing_guide', guidedResponse(cat), 'gentle', true,
                '孩子感到害怕，需要安抚', 60, 'high', 'fearful');
        }
        if (attention < ATTENTION_THRESHOLD_CRITICAL) {
            return plan('gentle_redirect', '小予在这里呢，我们一起来看看这个好吗？',
                'playful', false, '', 15, 'medium', 'attention_critical');
        }
        if (cat === 'anxious') {
            return plan('breathing_guide', guidedResponse(cat), 'calm', false, '', 45, 'medium', 'anxious');
        }
        if (cat === 'sad') {
            return plan('emotion_label', guidedResponse(cat), 'gentle', false, '', 30, 'medium', 'sad');
        }
        if (cat === 'angry') {
            return plan('emotion_label', guidedResponse(cat), 'calm', false, '', 45, 'medium', 'angry');
        }
        if (attention < ATTENTION_THRESHOLD_LOW) {
            return plan('gentle_redirect', '你想和小予一起玩吗？',
                'playful', false, '', 10, 'low', 'attention_low');
        }
        if (cat === 'happy' || cat === 'surprised') {
            return plan('positive_reinforce', guidedResponse(cat), 'playful', false, '', 10, 'low', 'positive');
        }
        return plan('none', '', 'gentle', false, '', 0, 'low', 'none');
    }

    // ─────────────────────────────────────────────────────────────────
    // 实时情绪模拟（随机游走 + 偶发事件，缓慢演化）
    // ─────────────────────────────────────────────────────────────────

    var sim = {
        initialized: false,
        initializedAt: Date.now(),
        lastTick: 0,
        mood: 0.1,              // -1..1 潜在情绪（负=不愉快）
        energy: 0.5,            // 0..1 潜在唤醒度
        attentionEvent: 0,      // 注意力流失事件剩余秒数
        attentionLossTime: 0,   // 视觉"人脸丢失"累计秒数（用于注意力衰减）
        anxietyEvent: 0,        // 短暂焦虑事件剩余秒数
        distressEvent: 0,       // 偶发过载事件剩余秒数
        eventCooldown: 12,
        cycleCount: 0,
        lastState: null,
        lastBehavior: null,
        lastIntervention: null
    };

    /** 由潜在状态推断"真值"情绪类别。 */
    function latentCategory() {
        if (sim.distressEvent > 0) return 'distressed';
        if (sim.anxietyEvent > 0) return 'anxious';

        var m = sim.mood, e = sim.energy;
        if (m > 0.45) return 'happy';
        if (m > 0.12) return e > 0.65 ? 'surprised' : 'calm';
        if (m > -0.15) return 'neutral';
        if (m > -0.45) return e > 0.6 ? 'angry' : 'sad';
        return 'sad';
    }

    /** 潜在类别 → 视觉原始标签（注意视觉无法产出 distressed）。 */
    var LATENT_TO_VISION = {
        happy: 'happy', surprised: 'surprise', calm: 'neutral', neutral: 'neutral',
        anxious: 'anxious', sad: 'sad', angry: 'angry', fearful: 'fear',
        distressed: 'fear'
    };

    /** 潜在类别 → 语音原始标签。 */
    var LATENT_TO_SPEECH = {
        happy: 'happy', surprised: 'neutral', calm: 'neutral', neutral: 'neutral',
        anxious: 'anxious', sad: 'sad', angry: 'angry', fearful: 'anxious',
        distressed: 'anxious'
    };

    /** 采集一帧三模态输入。 */
    function sampleModalities(hour, latent) {
        // ── 视觉通道 ──
        var visionState;
        var visionMissing = Math.random() < 0.08; // 偶发视觉掉线 → 注意力未知 0.5
        if (sim.attentionEvent > 0) {
            // 孩子在东张西望 → 明确报告人脸丢失，注意力按时长衰减
            visionState = { face_detected: false, attention_loss_time: sim.attentionLossTime };
        } else if (visionMissing) {
            visionState = {};
        } else {
            var vRaw = has(LATENT_TO_VISION, latent) ? LATENT_TO_VISION[latent] : 'neutral';
            // 少量噪声：偶尔把视觉判成中性（更贴近真实误判）
            if (Math.random() < 0.1) vRaw = 'neutral';
            visionState = { face_detected: true, emotion: vRaw };
        }

        // ── 语音通道（孩子约 35% 时间在说话）──
        var speechState = null;
        if (Math.random() < 0.35) {
            var sRaw = has(LATENT_TO_SPEECH, latent) ? LATENT_TO_SPEECH[latent] : 'neutral';
            var pool = has(SPEECH_POOL, latent) ? SPEECH_POOL[latent] : SPEECH_POOL.neutral;
            speechState = { emotion: sRaw, text: pick(pool, Math.random), seq: sim.cycleCount };
        }

        // ── 环境通道 ──
        var bioBase = 0.35 - sim.mood * 0.30;
        if (sim.anxietyEvent > 0) bioBase += 0.35;
        if (sim.distressEvent > 0) bioBase += 0.55;
        var bioAnxiety = round(clamp(bioBase + (Math.random() - 0.5) * 0.06, 0.0, 1.0), 3);
        var envSignals = { bio_anxiety: bioAnxiety, hour: hour };

        return { vision: visionState, speech: speechState, env: envSignals };
    }

    /** 推进一个时间步，返回当前 EmotionState（同步更新行为/干预缓存）。 */
    function evolve(dt) {
        dt = Math.max(0.2, dt);
        sim.cycleCount += 1;

        // 潜在状态随机游走（缓慢）
        sim.mood = clamp(sim.mood + (Math.random() - 0.5) * 0.05 * dt, -1.0, 1.0);
        sim.energy = clamp(sim.energy + (Math.random() - 0.5) * 0.04 * dt, 0.0, 1.0);

        // 偶发事件
        sim.eventCooldown -= dt;
        if (sim.eventCooldown <= 0) {
            var r = Math.random();
            if (r < 0.35) {
                sim.attentionEvent = 6 + Math.random() * 8;   // 注意力流失
                sim.attentionLossTime = 0;
            } else if (r < 0.62) {
                sim.anxietyEvent = 4 + Math.random() * 6;     // 短暂焦虑
            } else if (r < 0.70) {
                sim.distressEvent = 3 + Math.random() * 4;    // 偶发过载
            }
            sim.eventCooldown = 12 + Math.random() * 25;
        }

        sim.attentionEvent = Math.max(0, sim.attentionEvent - dt);
        sim.anxietyEvent = Math.max(0, sim.anxietyEvent - dt);
        sim.distressEvent = Math.max(0, sim.distressEvent - dt);

        if (sim.attentionEvent > 0) {
            sim.attentionLossTime = Math.min(10, sim.attentionLossTime + dt);
        } else {
            sim.attentionLossTime = 0;
        }

        // 事件对潜在情绪的影响
        if (sim.anxietyEvent > 0) sim.mood = clamp(sim.mood - 0.10 * dt, -1.0, 1.0);
        if (sim.distressEvent > 0) sim.mood = clamp(sim.mood - 0.16 * dt, -1.0, 1.0);

        var hour = new Date().getHours();
        var latent = latentCategory();
        var mod = sampleModalities(hour, latent);
        var state = fuse(mod.vision, mod.speech, mod.env);

        sim.lastState = state;
        sim.lastBehavior = buildBehavior(state);
        sim.lastIntervention = buildIntervention(state);
        return state;
    }

    /** 确保已初始化（惰性构建 30 天历史）。 */
    function ensureInit() {
        if (sim.initialized) return;
        sim.initialized = true;
        if (!sim.lastTick) sim.lastTick = Date.now();
        if (!historyRecords) historyRecords = buildHistory();
    }

    /** 取当前状态（每次调用推进演化）。 */
    function getCurrentState() {
        ensureInit();
        var now = Date.now();
        var dt = sim.lastTick ? (now - sim.lastTick) / 1000 : 0.5;
        sim.lastTick = now;
        return evolve(dt);
    }

    /** 读取最近一次状态；若尚无则推进一小步。 */
    function peekState() {
        ensureInit();
        if (!sim.lastState) return evolve(0.3);
        return sim.lastState;
    }

    // ─────────────────────────────────────────────────────────────────
    // 30 天合成历史（固定种子 → 决定论）
    // ─────────────────────────────────────────────────────────────────

    var HISTORY_DAYS = 30;
    var SAMPLE_INTERVAL_MIN = 120;               // 每 2 小时一条
    var HISTORY_SEED = 20240613;                 // 固定种子
    var BASE_NOW = Date.now();                   // 本次加载的时间锚点

    var historyRecords = null;

    /** 按小时分布的类别权重（白天偏积极、傍晚偏焦虑、夜间偏平静）。 */
    function historyCategoryWeights(hour) {
        var w = {
            neutral: 0.30, calm: 0.20, happy: 0.18, anxious: 0.10,
            sad: 0.08, surprised: 0.06, angry: 0.04, fearful: 0.02, distressed: 0.02
        };
        if (hour >= 7 && hour <= 11) { w.happy += 0.12; w.neutral -= 0.04; w.anxious -= 0.03; }
        else if (hour >= 12 && hour <= 17) { w.calm += 0.05; w.happy += 0.04; w.anxious -= 0.02; }
        else if (hour >= 18 && hour <= 21) { w.anxious += 0.12; w.sad += 0.05; w.happy -= 0.05; w.calm -= 0.05; }
        else { w.calm += 0.18; w.happy -= 0.10; w.neutral -= 0.05; } // 夜间/凌晨
        return w;
    }

    function weightedPick(weights, rng) {
        var total = 0, k;
        for (k in weights) if (has(weights, k)) total += weights[k];
        var r = rng() * total;
        for (k in weights) {
            if (!has(weights, k)) continue;
            r -= weights[k];
            if (r <= 0) return k;
        }
        return 'neutral';
    }

    function buildHistory() {
        var rng = mulberry32(HISTORY_SEED);
        var records = [];
        var totalSamples = Math.floor((HISTORY_DAYS * 24 * 60) / SAMPLE_INTERVAL_MIN); // 360

        for (var i = totalSamples - 1; i >= 0; i--) {
            var ts = BASE_NOW - i * SAMPLE_INTERVAL_MIN * 60 * 1000;
            var hour = new Date(ts).getHours();
            var cat = weightedPick(historyCategoryWeights(hour), rng);

            var valence = clamp((has(EMOTION_VALENCE, cat) ? EMOTION_VALENCE[cat] : 0.0) + (rng() - 0.5) * 0.12, -1.0, 1.0);
            var arousal = clamp((has(EMOTION_AROUSAL, cat) ? EMOTION_AROUSAL[cat] : 0.5) + (rng() - 0.5) * 0.12, 0.0, 1.0);

            records.push({
                timestamp: localIso(ts),
                category: cat,
                valence: round(valence, 3),
                arousal: round(arousal, 3),
                cause: '',
                context: '',
                source_text: ''
            });
        }
        return records;
    }

    function recordsSince(days) {
        ensureInit();
        var cutoff = BASE_NOW - days * 24 * 60 * 60 * 1000;
        var out = [];
        for (var i = 0; i < historyRecords.length; i++) {
            if (Date.parse(historyRecords[i].timestamp) >= cutoff) out.push(historyRecords[i]);
        }
        return out;
    }

    function countByCategory(records) {
        var counts = {};
        for (var i = 0; i < records.length; i++) {
            var c = records[i].category;
            counts[c] = (counts[c] || 0) + 1;
        }
        return counts;
    }

    // ─────────────────────────────────────────────────────────────────
    // URL 处理器（返回结构与 web/api.py 逐字段一致）
    // ─────────────────────────────────────────────────────────────────

    function parseUrl(url) {
        var path = url, query = '';
        var qi = url.indexOf('?');
        if (qi >= 0) { path = url.slice(0, qi); query = url.slice(qi + 1); }
        // 去掉可能的 origin / 前缀，只保留 /api 起始部分
        var ai = path.indexOf('/api/');
        if (ai > 0) path = path.slice(ai);
        var params = {};
        if (query) {
            var pairs = query.split('&');
            for (var i = 0; i < pairs.length; i++) {
                if (!pairs[i]) continue;
                var kv = pairs[i].split('=');
                params[decodeURIComponent(kv[0])] = kv.length > 1 ? decodeURIComponent(kv[1]) : '';
            }
        }
        return { path: path, params: params };
    }

    function intParam(v, dflt) {
        var n = parseInt(v, 10);
        return isNaN(n) ? dflt : n;
    }

    function getEmotionCurrent() {
        var s = getCurrentState();
        return {
            category: s.category,
            confidence: s.confidence,
            valence: s.valence,
            arousal: s.arousal,
            vision_emotion: s.vision_emotion,
            speech_emotion: s.speech_emotion,
            environment_signal: s.environment_signal,
            emotional_cause: s.emotional_cause,
            attention_level: s.attention_level,
            timestamp: s.timestamp
        };
    }

    function getBehaviorCommand() {
        var s = peekState();
        var cmd = sim.lastBehavior || buildBehavior(s);
        return {
            actions: cmd.actions.slice(),
            speech_rate: cmd.speech_rate,
            led_color: cmd.led_color,
            led_brightness: cmd.led_brightness,
            servo_speed: cmd.servo_speed,
            priority: cmd.priority,
            reason: cmd.reason
        };
    }

    function getBehaviorStatus() {
        var cmd = sim.lastBehavior;
        return {
            hardware_available: false,
            current_action: (cmd && cmd.actions.length) ? cmd.actions[0] : null,
            running: true
        };
    }

    function getEmotionTrends(period) {
        var windows = {
            hourly: 60 * 60 * 1000,
            daily: 24 * 60 * 60 * 1000,
            weekly: 7 * 24 * 60 * 60 * 1000
        };
        var win = has(windows, period) ? windows[period] : windows.daily;
        ensureInit();
        var cutoff = BASE_NOW - win;
        var recs = [];
        for (var i = 0; i < historyRecords.length; i++) {
            if (Date.parse(historyRecords[i].timestamp) >= cutoff) recs.push(historyRecords[i]);
        }

        if (recs.length === 0) {
            return {
                period: period, dominant_emotion: 'neutral', average_valence: 0.0,
                average_arousal: 0.5, stability_score: 1.0,
                risk_periods: [], positive_periods: [], total_records: 0
            };
        }

        var counts = countByCategory(recs);
        var dominant = 'neutral', best = -1;
        for (var j = 0; j < recs.length; j++) {
            var c = recs[j].category;
            if (counts[c] > best) { best = counts[c]; dominant = c; }
        }

        var valences = [], arousals = [];
        for (var k = 0; k < recs.length; k++) { valences.push(recs[k].valence); arousals.push(recs[k].arousal); }
        var avgValence = average(valences);

        var stability = 1.0;
        if (recs.length > 1) {
            var variance = 0;
            for (var v = 0; v < valences.length; v++) variance += Math.pow(valences[v] - avgValence, 2);
            variance /= valences.length;
            stability = Math.max(0.0, 1.0 - Math.sqrt(variance));
        }

        var risk = [], pos = [];
        for (var t = 0; t < recs.length; t++) {
            if (recs[t].valence < -0.3) risk.push(recs[t].timestamp);
            if (recs[t].valence > 0.3) pos.push(recs[t].timestamp);
        }

        return {
            period: period,
            dominant_emotion: dominant,
            average_valence: round(avgValence, 3),
            average_arousal: round(average(arousals), 3),
            stability_score: round(stability, 3),
            risk_periods: risk.slice(-10),
            positive_periods: pos.slice(-10),
            total_records: recs.length
        };
    }

    function getValenceSeries(days) {
        ensureInit();
        var cutoff = BASE_NOW - days * 24 * 60 * 60 * 1000;
        var series = [];
        for (var i = 0; i < historyRecords.length; i++) {
            if (Date.parse(historyRecords[i].timestamp) >= cutoff) {
                series.push({ timestamp: historyRecords[i].timestamp, valence: historyRecords[i].valence });
            }
        }
        return { series: series, days: days };
    }

    function getEmotionCounts(days) {
        var recs = recordsSince(days);
        return { counts: countByCategory(recs), days: days };
    }

    function getParentReport(days) {
        var recs = recordsSince(days);
        var counts = countByCategory(recs);
        var trend = getEmotionTrends('weekly');

        var total = recs.length;
        var positive = (counts.happy || 0) + (counts.calm || 0);
        var negative = (counts.sad || 0) + (counts.anxious || 0) + (counts.distressed || 0);

        // ── 概述（镜像 intervention.generate_parent_report 的判定）──
        var summary;
        if (total < 5) {
            summary = '本周互动记录较少，建议增加与小予的互动时间。';
        } else if (positive > negative * 2) {
            summary = '本周整体情绪状态良好，孩子表现出较多积极情绪。';
        } else if (negative > positive) {
            summary = '本周情绪波动较多，建议关注孩子的情绪变化。';
        } else {
            summary = '本周情绪状态平稳，有正常的起伏变化。';
        }

        // ── 亮点 ──
        var highlights = [];
        if (counts.happy) highlights.push('开心时刻 ' + counts.happy + ' 次');
        if (trend.stability_score > 0.7) highlights.push('情绪稳定性良好');

        // ── 关注 ──
        var concerns = [];
        if (counts.distressed) concerns.push('出现 ' + counts.distressed + ' 次过载状态');
        if (trend.average_valence < -0.3) concerns.push('整体情绪偏负面');

        // ── 建议 ──
        var suggestions = [];
        if ((counts.anxious || 0) > 3) suggestions.push('建议减少环境刺激，创造安静舒适的互动空间');
        if ((counts.sad || 0) > 2) suggestions.push('建议增加亲子互动时间，多给予肯定和鼓励');
        if (highlights.length === 0) suggestions.push('建议增加与小予的互动频率');
        if (trend.stability_score < 0.5) suggestions.push('建议保持规律的作息时间，减少突发变化');

        // ── 健康指数 ──
        // 演示数据密度较高，若照搬真实公式（positive*5 - negative*10）会长期顶到 100，
        // 失去区分度。这里改用"比例化"评分，落到合理区间且仍反映正/负情绪与稳定性。
        var positiveRate = total ? positive / total : 0;
        var negativeRate = total ? negative / total : 0;
        var health = 50 + (positiveRate - negativeRate) * 60 + (trend.stability_score - 0.5) * 40;
        health = clamp(health, 0.0, 100.0);

        return {
            period_start: localDate(BASE_NOW - days * 24 * 60 * 60 * 1000),
            period_end: localDate(BASE_NOW),
            summary: summary,
            emotion_trend: {
                period: 'weekly',
                dominant_emotion: trend.dominant_emotion,
                average_valence: trend.average_valence,
                stability_score: trend.stability_score
            },
            highlights: highlights,
            concerns: concerns,
            suggestions: suggestions,
            interaction_count: total,
            health_score: round(health, 1)
        };
    }

    function getRiskTriggers(windowMinutes) {
        var cur = peekState();
        var triggers = [];

        if (cur.category === 'distressed') triggers.push('孩子出现过载状态，建议减少环境刺激');
        else if (cur.category === 'fearful') triggers.push('孩子感到害怕，需要安抚');
        if (cur.attention_level < ATTENTION_THRESHOLD_CRITICAL) triggers.push('注意力严重流失，建议温和吸引');

        // 叠加窗口内的持续负面情绪检测
        ensureInit();
        var cutoff = BASE_NOW - windowMinutes * 60 * 1000;
        var negCount = 0;
        for (var i = 0; i < historyRecords.length; i++) {
            if (Date.parse(historyRecords[i].timestamp) >= cutoff && historyRecords[i].valence < -0.3) negCount++;
        }
        if (negCount >= 3) triggers.push('持续负面情绪 (' + negCount + '次)');

        return {
            triggers: triggers,
            has_risk: triggers.length > 0,
            window_minutes: windowMinutes
        };
    }

    function getSystemStatus() {
        return {
            status: 'standalone',
            timestamp: localIso(Date.now()),
            bridge: { connected: false, running: false },
            modules: {
                fusion_engine: true,
                memory_axis: true,
                behavior_sync: true,
                embodied_engine: true,
                intervention_engine: true
            },
            version: '1.1.0'
        };
    }

    function getBridgeStatus() {
        var s = peekState();
        return {
            connected: true,
            is_running: true,
            cycle_count: sim.cycleCount,
            last_update: s.timestamp,
            attention_level: s.attention_level
        };
    }

    function getLastIntervention() {
        var s = peekState();
        var plan = sim.lastIntervention || buildIntervention(s);
        return {
            intervention_type: plan.intervention_type,
            guidance_text: plan.guidance_text,
            guidance_style: plan.guidance_style,
            parent_alert: plan.parent_alert,
            parent_note: plan.parent_note,
            duration_seconds: plan.duration_seconds,
            metadata: plan.metadata
        };
    }

    // ─────────────────────────────────────────────────────────────────
    // 对外接口
    // ─────────────────────────────────────────────────────────────────

    /**
     * 同步返回指定 URL 对应的演示数据。
     * @param {string} url 形如 '/api/emotion/current' 或带查询串的 URL。
     * @returns {object|null} 与 web/api.py 同构的 JSON 对象；未知 URL 返回 null。
     */
    function get(url) {
        if (typeof url !== 'string') return null;
        ensureInit();
        var parsed = parseUrl(url);
        var path = parsed.path;
        var p = parsed.params;

        switch (path) {
            case '/api/emotion/current':
                return getEmotionCurrent();
            case '/api/behavior/command':
                return getBehaviorCommand();
            case '/api/behavior/status':
                return getBehaviorStatus();
            case '/api/emotion/trends':
                return getEmotionTrends(p.period || 'daily');
            case '/api/emotion/valence-series':
                return getValenceSeries(intParam(p.days, 7));
            case '/api/emotion/counts':
                return getEmotionCounts(intParam(p.days, 7));
            case '/api/parent/report':
                return getParentReport(intParam(p.days, 7));
            case '/api/risk/triggers':
                return getRiskTriggers(intParam(p.window_minutes, 60));
            case '/api/system/status':
                return getSystemStatus();
            case '/api/bridge/status':
                return getBridgeStatus();
            case '/api/intervention/last':
                return getLastIntervention();
            default:
                return null;
        }
    }

    /** 演示引擎是否可用（本次加载已就绪）。 */
    function isActive() {
        return true;
    }

    global.SoulCompanionDemo = {
        get: get,
        isActive: isActive,
        // 便于诊断（非对外契约）：暴露类别集合
        categories: CATEGORIES.slice()
    };
})(typeof window !== 'undefined' ? window : this);
