export interface ActivationEvent {
  key: string;
  repeat?: boolean;
  preventDefault(): void;
}

export function activateOnKey(event: ActivationEvent, activate: (() => void) | undefined, disabled = false): void {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  if (!disabled && !event.repeat) activate?.();
}
