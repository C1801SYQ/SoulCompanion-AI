import { describe, expect, it } from 'vitest';
import { componentLabel, emotionLabel, visibleComponentNames } from '../src/components/format';

describe('emotion label fallback', () => {
  it('translates known categories without changing future category text', () => {
    expect(emotionLabel('HAPPY')).toBe('愉悦');
    expect(emotionLabel('future_emotion')).toBe('future_emotion');
    expect(emotionLabel('专注')).toBe('专注');
  });

  it.each(['__proto__', 'constructor', 'toString', 'valueOf', 'hasOwnProperty', '__defineGetter__'])(
    'renders reserved category %s as text instead of inheriting object properties',
    category => {
      const label = emotionLabel(category);
      expect(label).toBe(category);
      expect(typeof label).toBe('string');
    },
  );
});

describe('system component labels', () => {
  it('limits the settings display to the ten validated component contracts', () => {
    expect(visibleComponentNames).toHaveLength(10);
    expect(visibleComponentNames).toContain('camera');
    expect(visibleComponentNames).not.toContain('__proto__');
    expect(componentLabel('database')).toBe('情绪记录存储');
  });

  it.each(['__proto__', 'constructor', 'toString', 'future_component'])(
    'keeps unknown component %s as text',
    name => expect(componentLabel(name)).toBe(name),
  );
});
