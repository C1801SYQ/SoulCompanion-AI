export interface KeyboardHeightEvent { height: number }
export type KeyboardHeightListener = (event: KeyboardHeightEvent) => void;
export interface KeyboardHeightAdapter {
  onKeyboardHeightChange(listener: KeyboardHeightListener): void;
  offKeyboardHeightChange(listener: KeyboardHeightListener): void;
}

/** Each visible page owns its listener; callbacks from an old page cannot hide the next page's rail. */
export function createKeyboardHeightLifecycle(
  adapter: KeyboardHeightAdapter,
  onHeight: (height: number) => void,
  onFailure: () => void,
) {
  let generation = 0;
  let listener: KeyboardHeightListener | null = null;
  let disposed = false;
  function hide() {
    generation++;
    const previous = listener;
    listener = null;
    if (previous) {
      try { adapter.offKeyboardHeightChange(previous); } catch { onFailure(); }
    }
    if (!disposed) onHeight(0);
  }
  return {
    show() {
      if (disposed || listener) return;
      const current = ++generation;
      const next: KeyboardHeightListener = event => {
        if (disposed || current !== generation) return;
        onHeight(Number.isFinite(event.height) ? Math.max(0, event.height) : 0);
      };
      listener = next;
      try { adapter.onKeyboardHeightChange(next); } catch {
        hide();
        onFailure();
      }
    },
    hide,
    dispose() {
      if (disposed) return;
      disposed = true;
      hide();
    },
  };
}
