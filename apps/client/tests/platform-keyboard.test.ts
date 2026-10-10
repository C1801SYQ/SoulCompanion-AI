import { describe, expect, it, vi } from 'vitest';
import { createKeyboardHeightLifecycle, type KeyboardHeightListener } from '../src/platform/keyboardLifecycle';

function setup() {
  const callbacks: KeyboardHeightListener[] = [];
  const adapter = {
    onKeyboardHeightChange: vi.fn((listener: KeyboardHeightListener) => { callbacks.push(listener); }),
    offKeyboardHeightChange: vi.fn(),
  };
  const onHeight = vi.fn();
  const onFailure = vi.fn();
  const lifecycle = createKeyboardHeightLifecycle(adapter, onHeight, onFailure);
  return { adapter, callbacks, onHeight, onFailure, lifecycle };
}

describe('visible WeChat page keyboard lifecycle', () => {
  it('subscribes once and exposes measured keyboard height rather than a focus guess', () => {
    const { lifecycle, adapter, callbacks, onHeight } = setup();
    lifecycle.show(); lifecycle.show();
    expect(adapter.onKeyboardHeightChange).toHaveBeenCalledTimes(1);
    callbacks[0]({ height: 312 });
    expect(onHeight).toHaveBeenLastCalledWith(312);
    callbacks[0]({ height: 0 });
    expect(onHeight).toHaveBeenLastCalledWith(0);
  });

  it('removes only its own callback and ignores late events when a page hides or returns', () => {
    const { lifecycle, adapter, callbacks, onHeight } = setup();
    lifecycle.show();
    callbacks[0]({ height: 280 });
    lifecycle.hide();
    expect(adapter.offKeyboardHeightChange).toHaveBeenCalledWith(callbacks[0]);
    expect(onHeight).toHaveBeenLastCalledWith(0);
    onHeight.mockClear();
    callbacks[0]({ height: 280 });
    expect(onHeight).not.toHaveBeenCalled();
    lifecycle.show();
    callbacks[0]({ height: 280 });
    expect(onHeight).not.toHaveBeenCalled();
    callbacks[1]({ height: 300 });
    expect(onHeight).toHaveBeenLastCalledWith(300);
  });

  it('cleans up on unmount and cannot be reactivated or update an unmounted page', () => {
    const { lifecycle, adapter, callbacks, onHeight } = setup();
    lifecycle.show();
    onHeight.mockClear();
    lifecycle.dispose(); lifecycle.dispose(); lifecycle.show();
    expect(adapter.offKeyboardHeightChange).toHaveBeenCalledTimes(1);
    callbacks[0]({ height: 330 });
    expect(onHeight).not.toHaveBeenCalled();
    expect(adapter.onKeyboardHeightChange).toHaveBeenCalledTimes(1);
  });

  it('rejects invalid native measurements and reports listener failures without trapping navigation', () => {
    const { lifecycle, adapter, callbacks, onHeight, onFailure } = setup();
    lifecycle.show();
    for (const height of [-1, NaN, Infinity]) {
      callbacks[0]({ height });
      expect(onHeight).toHaveBeenLastCalledWith(0);
    }
    adapter.offKeyboardHeightChange.mockImplementation(() => { throw new Error('unavailable'); });
    expect(() => lifecycle.hide()).not.toThrow();
    expect(onFailure).toHaveBeenCalledTimes(1);
    adapter.onKeyboardHeightChange.mockImplementation(() => { throw new Error('unavailable'); });
    expect(() => lifecycle.show()).not.toThrow();
    expect(onFailure).toHaveBeenCalled();
  });
});
