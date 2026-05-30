"""
emotion/intervention.py - Education-oriented Intervention System

Generates gentle, non-commanding interventions for ASD children.
Follows strict ASD intervention principles:
- NEVER command or order the child
- NEVER criticize or correct
- ALWAYS use guiding, gentle language
- ALWAYS respect the child's emotional state
- Output parent reports in a non-intrusive way

Input:  EmotionState + context
Output: InterventionPlan + ParentReport
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from emotion.memory_axis import MemoryAxis
from emotion.models import (
    EmotionCategory,
    EmotionState,
    EmotionTrend,
    InterventionPlan,
    InterventionType,
    ParentReport,
)

logger = logging.getLogger("Intervention")

# ─── Guiding Language Templates ────────────────────────────────────────
# All language is gentle, non-commanding, and child-friendly.
# These are templates; the LLM can also generate custom responses.

GUIDED_RESPONSES: Dict[EmotionCategory, List[str]] = {
    EmotionCategory.HAPPY: [
        "你今天看起来好开心呀！能告诉小予是什么让你这么高兴吗？",
        "哇，你的笑容好温暖！小予也很开心呢。",
        "你做得真棒！我们一起来玩个游戏好不好？",
    ],
    EmotionCategory.CALM: [
        "你今天很安静呢，小予陪着你哦。",
        "我们一起来做深呼吸好不好？吸——呼——",
        "你看起来很放松，这样真好。",
    ],
    EmotionCategory.NEUTRAL: [
        "小予在这里呢，你想聊点什么吗？",
        "我们一起来看看这个有趣的东西吧。",
        "你想听小予讲个故事吗？",
    ],
    EmotionCategory.SURPRISED: [
        "哇，你发现了什么有趣的东西呀？",
        "你的眼睛亮起来了！能告诉小予吗？",
        "好神奇呀！我们一起来探索吧。",
    ],
    EmotionCategory.ANXIOUS: [
        "小予感觉到你有点紧张，没关系的，小予陪着你。",
        "我们一起来做深呼吸好吗？吸气——慢慢呼气——",
        "你可以抱抱小予，小予会一直在这里。",
        "没关系的，慢慢来，不着急。",
    ],
    EmotionCategory.SAD: [
        "你看起来有点难过，小予想陪着你。",
        "你可以告诉小予发生了什么，小予会听你说。",
        "每个人都会有难过的时候，没关系的。",
        "小予给你一个温暖的抱抱好不好？",
    ],
    EmotionCategory.ANGRY: [
        "你看起来有点生气，小予理解你的感受。",
        "我们可以一起做深呼吸，让心情慢慢平静下来。",
        "你愿意告诉小予是什么让你不开心吗？",
        "没关系，生气是正常的，我们慢慢来。",
    ],
    EmotionCategory.FEARFUL: [
        "小予在这里，你不用害怕。",
        "你可以抓住小予的手，小予会保护你。",
        "我们一起来做深呼吸，让心情慢慢平静。",
        "你很勇敢的，小予相信你。",
    ],
    EmotionCategory.DISTRESSED: [
        "小予在这里陪着你，你不是一个人。",
        "我们慢慢来，不着急，小予会一直在这里。",
        "你可以抱抱小予，让小予帮你放松。",
        "深呼吸，吸——呼——，慢慢来。",
    ],
}

# ─── Intervention Thresholds ───────────────────────────────────────────

# Valence thresholds for triggering interventions
INTERVENTION_THRESHOLDS = {
    "gentle_redirect": -0.2,    # Mild negative → gentle redirect
    "emotion_label": -0.4,      # Moderate negative → help label emotion
    "breathing_guide": -0.5,    # Significant negative → breathing guide
    "calming_activity": -0.7,   # High negative → calming activity
}

# Attention thresholds
ATTENTION_THRESHOLD_LOW = 0.3
ATTENTION_THRESHOLD_CRITICAL = 0.1


class InterventionEngine:
    """
    Education-oriented intervention system for ASD children.

    Core principles:
    1. Never command or order the child
    2. Never criticize or correct behavior
    3. Always use gentle, guiding language
    4. Always respect the child's emotional state
    5. Provide parent reports in a non-intrusive way

    Generates InterventionPlans based on EmotionState and context.
    """

    def __init__(self, memory_axis: Optional[MemoryAxis] = None):
        self.memory_axis = memory_axis
        self._last_plan = InterventionPlan()
        self._intervention_count = 0
        self._last_intervention_time: Optional[datetime] = None

        # Cooldown: minimum seconds between interventions
        self.cooldown_seconds = 30

        logger.info("✅ [干预引擎] 教育型干预系统已就绪")

    def evaluate(self, state: EmotionState, context: str = "") -> InterventionPlan:
        """
        Evaluate the current emotional state and generate an intervention plan.

        Args:
            state: Current fused EmotionState
            context: What is happening (e.g., "自由对话")

        Returns:
            InterventionPlan with guidance text and type
        """
        # Check cooldown
        if self._is_in_cooldown():
            return InterventionPlan(intervention_type=InterventionType.NONE)

        # Evaluate intervention need
        plan = self._evaluate_intervention(state, context)

        if plan.intervention_type != InterventionType.NONE:
            self._last_plan = plan
            self._intervention_count += 1
            self._last_intervention_time = datetime.now()

        return plan

    def _evaluate_intervention(self, state: EmotionState, context: str) -> InterventionPlan:
        """Determine what type of intervention is needed."""
        category = state.category
        valence = state.valence
        attention = state.attention_level

        # ── Priority 1: Distressed/Overload (highest urgency) ──
        if category == EmotionCategory.DISTRESSED:
            return InterventionPlan(
                intervention_type=InterventionType.CALMING_ACTIVITY,
                guidance_text=self._select_guided_response(category),
                guidance_style="calm",
                parent_alert=True,
                parent_note="孩子出现过载状态，建议减少环境刺激",
                duration_seconds=120,
                metadata={"urgency": "high", "reason": "distressed"},
            )

        # ── Priority 2: Fearful ──
        if category == EmotionCategory.FEARFUL:
            return InterventionPlan(
                intervention_type=InterventionType.BREATHING_GUIDE,
                guidance_text=self._select_guided_response(category),
                guidance_style="gentle",
                parent_alert=True,
                parent_note="孩子感到害怕，需要安抚",
                duration_seconds=60,
                metadata={"urgency": "high", "reason": "fearful"},
            )

        # ── Priority 3: Attention lost ──
        if attention < ATTENTION_THRESHOLD_CRITICAL:
            return InterventionPlan(
                intervention_type=InterventionType.GENTLE_REDIRECT,
                guidance_text="小予在这里呢，我们一起来看看这个好吗？",
                guidance_style="playful",
                parent_alert=False,
                duration_seconds=15,
                metadata={"urgency": "medium", "reason": "attention_critical"},
            )

        # ── Priority 4: Anxiety ──
        if category == EmotionCategory.ANXIOUS:
            return InterventionPlan(
                intervention_type=InterventionType.BREATHING_GUIDE,
                guidance_text=self._select_guided_response(category),
                guidance_style="calm",
                parent_alert=False,
                duration_seconds=45,
                metadata={"urgency": "medium", "reason": "anxious"},
            )

        # ── Priority 5: Sadness ──
        if category == EmotionCategory.SAD:
            return InterventionPlan(
                intervention_type=InterventionType.EMOTION_LABEL,
                guidance_text=self._select_guided_response(category),
                guidance_style="gentle",
                parent_alert=False,
                duration_seconds=30,
                metadata={"urgency": "medium", "reason": "sad"},
            )

        # ── Priority 6: Anger ──
        if category == EmotionCategory.ANGRY:
            return InterventionPlan(
                intervention_type=InterventionType.EMOTION_LABEL,
                guidance_text=self._select_guided_response(category),
                guidance_style="calm",
                parent_alert=False,
                duration_seconds=45,
                metadata={"urgency": "medium", "reason": "angry"},
            )

        # ── Priority 7: Low attention (mild) ──
        if attention < ATTENTION_THRESHOLD_LOW:
            return InterventionPlan(
                intervention_type=InterventionType.GENTLE_REDIRECT,
                guidance_text="你想和小予一起玩吗？",
                guidance_style="playful",
                parent_alert=False,
                duration_seconds=10,
                metadata={"urgency": "low", "reason": "attention_low"},
            )

        # ── Priority 8: Positive reinforcement opportunity ──
        if category in (EmotionCategory.HAPPY, EmotionCategory.SURPRISED):
            return InterventionPlan(
                intervention_type=InterventionType.POSITIVE_REINFORCE,
                guidance_text=self._select_guided_response(category),
                guidance_style="playful",
                parent_alert=False,
                duration_seconds=10,
                metadata={"urgency": "low", "reason": "positive"},
            )

        # No intervention needed
        return InterventionPlan(intervention_type=InterventionType.NONE)

    def _select_guided_response(self, category: EmotionCategory) -> str:
        """Select a guided response from templates."""
        import random
        responses = GUIDED_RESPONSES.get(category, GUIDED_RESPONSES[EmotionCategory.NEUTRAL])
        return random.choice(responses)

    def _is_in_cooldown(self) -> bool:
        """Check if we're still in cooldown period."""
        if self._last_intervention_time is None:
            return False
        elapsed = (datetime.now() - self._last_intervention_time).total_seconds()
        return elapsed < self.cooldown_seconds

    def get_last_plan(self) -> InterventionPlan:
        """Return the most recent InterventionPlan."""
        return self._last_plan

    # ─── Parent Report Generation ─────────────────────────────────────

    def generate_parent_report(
        self, memory_axis: Optional[MemoryAxis] = None, days: int = 7
    ) -> ParentReport:
        """
        Generate a weekly parent report.
        Non-intrusive: summary format, not alarmist.

        Args:
            memory_axis: Memory axis for data (uses self.memory_axis if None)
            days: Number of days to cover

        Returns:
            ParentReport with summary, highlights, concerns, suggestions
        """
        axis = memory_axis or self.memory_axis
        if axis is None:
            logger.warning("⚠️ [家长报告] 无法生成报告：缺少记忆轴")
            return ParentReport(
                period_start=datetime.now().strftime("%Y-%m-%d"),
                period_end=datetime.now().strftime("%Y-%m-%d"),
                summary="暂无足够数据生成报告",
            )

        now = datetime.now()
        start = now - timedelta(days=days)

        # Get trend analysis
        trend = axis.get_trend_analysis(period="weekly")

        # Get emotion counts
        emotion_counts = axis.get_emotion_counts(days=days)

        # Get risk triggers
        risk_triggers = axis.check_risk_triggers(window_minutes=60 * 24 * days)

        # Get periodicity patterns
        patterns = axis.detect_periodicity(lookback_days=days)

        # ── Build summary ──
        total = sum(emotion_counts.values())
        positive = emotion_counts.get("happy", 0) + emotion_counts.get("calm", 0)
        negative = (
            emotion_counts.get("sad", 0)
            + emotion_counts.get("anxious", 0)
            + emotion_counts.get("distressed", 0)
        )

        if total == 0:
            summary = "本周互动记录较少，建议增加与小予的互动时间。"
        elif positive > negative * 2:
            summary = "本周整体情绪状态良好，孩子表现出较多积极情绪。"
        elif negative > positive:
            summary = "本周情绪波动较多，建议关注孩子的情绪变化。"
        else:
            summary = "本周情绪状态平稳，有正常的起伏变化。"

        # ── Build highlights ──
        highlights: List[str] = []
        if emotion_counts.get("happy", 0) > 0:
            highlights.append(f"开心时刻 {emotion_counts['happy']} 次")
        if trend.stability_score > 0.7:
            highlights.append("情绪稳定性良好")
        if patterns:
            positive_patterns = [k for k, v in patterns.items() if "positive" in k]
            if positive_patterns:
                highlights.append(f"发现积极情绪模式: {positive_patterns[0]}")

        # ── Build concerns ──
        concerns: List[str] = []
        if risk_triggers:
            concerns.extend(risk_triggers[:3])  # Top 3 concerns
        if emotion_counts.get("distressed", 0) > 0:
            concerns.append(f"出现 {emotion_counts['distressed']} 次过载状态")
        if trend.average_valence < -0.3:
            concerns.append("整体情绪偏负面")

        # ── Build suggestions ──
        suggestions: List[str] = []
        if emotion_counts.get("anxious", 0) > 3:
            suggestions.append("建议减少环境刺激，创造安静舒适的互动空间")
        if emotion_counts.get("sad", 0) > 2:
            suggestions.append("建议增加亲子互动时间，多给予肯定和鼓励")
        if not highlights:
            suggestions.append("建议增加与小予的互动频率")
        if trend.stability_score < 0.5:
            suggestions.append("建议保持规律的作息时间，减少突发变化")

        # ── Health score ──
        health_score = 50.0  # Base
        health_score += positive * 5
        health_score -= negative * 10
        health_score += trend.stability_score * 20
        health_score = max(0.0, min(100.0, health_score))

        return ParentReport(
            period_start=start.strftime("%Y-%m-%d"),
            period_end=now.strftime("%Y-%m-%d"),
            summary=summary,
            emotion_trend=trend,
            highlights=highlights,
            concerns=concerns,
            suggestions=suggestions,
            interaction_count=total,
            health_score=round(health_score, 1),
        )

    def generate_parent_report_markdown(self, days: int = 7) -> str:
        """Generate parent report as Markdown string."""
        report = self.generate_parent_report(days=days)

        md = f"""# 🌟 小予机器人 - 每周情感陪伴报告

**报告周期：** {report.period_start} ~ {report.period_end}

---

## 📊 本周总览

- **互动次数：** {report.interaction_count} 次
- **情绪健康指数：** {report.health_score} / 100
- **整体评价：** {report.summary}

---

## ✨ 本周亮点

"""
        if report.highlights:
            for h in report.highlights:
                md += f"- {h}\n"
        else:
            md += "- 本周暂无特别亮点\n"

        md += "\n---\n\n## ⚠️ 需要关注\n\n"

        if report.concerns:
            for c in report.concerns:
                md += f"- {c}\n"
        else:
            md += "- 本周无需特别关注\n"

        md += "\n---\n\n## 💡 建议\n\n"

        if report.suggestions:
            for s in report.suggestions:
                md += f"- {s}\n"
        else:
            md += "- 保持当前的互动方式即可\n"

        md += "\n---\n\n*此报告由小予智能系统自动生成，仅供参考。如有疑问，请咨询专业儿童心理医生。*\n"

        return md


def create_intervention_engine(memory_axis: Optional[MemoryAxis] = None) -> InterventionEngine:
    """Factory function to create an InterventionEngine instance."""
    return InterventionEngine(memory_axis=memory_axis)
