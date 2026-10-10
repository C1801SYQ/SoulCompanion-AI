/** Browser focus and viewport behavior stay native; no unsupported Taro keyboard listener is installed. */
export function useNavigationKeyboardHeight(): number { return 0; }
export const textInputKeyboardProps = {};
export async function dismissKeyboard(): Promise<void> {
  if (typeof document === 'undefined') return;
  const focused = document.activeElement;
  if (focused instanceof HTMLElement) focused.blur();
}
