import { describe, expect, it, vi } from 'vitest';
import { activateOnKey } from '../src/components/keyboard';

describe('cross-platform button keyboard activation', () => {
  it.each(['Enter', ' '])('activates exactly once for %s and stops default scrolling', key => {
    const activate = vi.fn();
    const preventDefault = vi.fn();
    activateOnKey({ key, preventDefault }, activate);
    expect(activate).toHaveBeenCalledTimes(1);
    expect(preventDefault).toHaveBeenCalledTimes(1);
  });

  it('does not activate a disabled control or repeatedly toggle a held key', () => {
    const activate = vi.fn();
    activateOnKey({ key: 'Enter', preventDefault: vi.fn() }, activate, true);
    activateOnKey({ key: ' ', repeat: true, preventDefault: vi.fn() }, activate);
    expect(activate).not.toHaveBeenCalled();
  });

  it.each(['Tab', 'Escape', 'ArrowRight'])('does not intercept %s navigation', key => {
    const activate = vi.fn();
    const preventDefault = vi.fn();
    activateOnKey({ key, preventDefault }, activate);
    expect(activate).not.toHaveBeenCalled();
    expect(preventDefault).not.toHaveBeenCalled();
  });
});
