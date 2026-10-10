/** Queued nextTick callbacks belong to one page-show frame, not a later visible page. */
export function createScrollRestoreLifecycle() {
  let generation = 0;
  let visible = true;
  let disposed = false;
  return {
    show(): number { visible = !disposed; return ++generation; },
    hide(): void { visible = false; generation++; },
    dispose(): void { visible = false; disposed = true; generation++; },
    isVisible(): boolean { return visible && !disposed; },
    isCurrent(frame: number): boolean { return visible && !disposed && generation === frame; },
  };
}
