# SoulCompanion V2 design direction

Planned on 2026-10-03 before UI implementation. The intended experience is a calm
place to start a short companionship session, understand an observation, and revisit
notes. It is neither a clinical assessment nor a robot engineering console.

## Tokens and composition

| Token | Value and role |
| --- | --- |
| Paper | `#FAFAF7`, quiet warm background |
| Surface | `#FFFFFF`, a small number of working areas |
| Ink | `#233A35`, readable text |
| Primary | `#265D57`, deep botanical green for actions |
| Mist | `#DCECE5`, supportive soft green |
| Warmth | `#D9AC70`, restrained amber in the emotion signature |
| Muted | `#60716B`, secondary text with readable contrast |
| Boundary | `#DAE3DC`, grouping and separators |
| Type | Platform Chinese sans-serif; consistent legible body and gently larger headings |
| Space | 4/8/12/16/24/32/48 px |
| Radius | 10 px controls, 20 px working surfaces, asymmetric Orb only |
| Shadow | Minimal on the Orb; structure otherwise uses spacing and borders |
| Motion | One slow 8–14 s breathing signature, max 3% size change, optional |

Desktop uses a quiet left navigation rail and left-aligned readable content, with
an open greeting/Orb composition and a smaller daily summary. Mobile places the
primary action within the first screen and five persistent bottom navigation items.
Details are divided across Home, Session, Insights, Reports and Profile/settings.

The Emotion Orb is the single memorable element. Valence adjusts its palette,
arousal changes gentle shape/breathing speed, and confidence limits glow strength.
No observation is a neutral resting shape with a clear empty-state label, never an
invented emotion. Text communicates all values independently of color or movement.
OS reduced-motion preferences and the in-product animation switch both disable
animation. No flashing, rapid oscillation, emoji signals or decorative page reveals.

## Review against the brief

An initial identical-card dashboard arrangement was rejected because it obscured
the companionship action and repeated the old engineering dashboard. The chosen
composition gives the Orb and start action room, with restrained summaries and
separate historical pages. There is no purple gradient, clinical blue, toy styling,
glass-card grid, or clinical interpretation of confidence/valence/arousal.

Navigation and controls use Taro primitives and Taroify public components. Shared
components do not depend on browser-only DOM libraries. Touch targets are at least
44 px; keyboard focus, labelled buttons, text status and contrast are required.
Device permissions are never requested while opening a page. Phase02 shows camera
and microphone OFF until actual client capture is implemented in Phase03.

## Reviewed sources

- [Anthropic frontend-design skill](https://github.com/anthropics/skills/tree/main/skills/frontend-design): product-specific direction, two-pass plan/critique and visual restraint; Apache-2.0. Read SKILL.md, LICENSE.txt and repository README.
- [Requested ui-ux-pro-max fork](https://github.com/Koubos/ui-ux-pro-max): UX/accessibility reference, MIT © 2024 Next Level Builder. Read its README, LICENSE and `.claude/skills/ui-ux-pro-max/SKILL.md`; it is a fork of nextlevelbuilder/ui-ux-pro-max-skill. The fork files were accessible despite a homepage fetch timeout.
- [Taroify](https://github.com/taroify/taroify): cross-platform components and public APIs, MIT © 2021-present Zhi Tang. Read README, LICENSE and the official [component skill](https://github.com/taroify/taroify/blob/main/packages/cli/skills/taroify/SKILL.md), not the unrelated Rspress website skills. Use documented public API and style imports.

Only reference text was read. No third-party installation script or skill code was
executed or installed. Dependency installation skips lifecycle scripts; any required
build-tool setup must be inspected separately before running it.
