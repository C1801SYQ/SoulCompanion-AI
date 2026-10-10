import { useEffect, useRef, useState } from 'react';
import Taro, { useDidHide, useDidShow } from '@tarojs/taro';
import { createKeyboardHeightLifecycle } from './keyboardLifecycle';

export const textInputKeyboardProps = { cursorSpacing: 24, adjustPosition: true } as const;
function reportKeyboardFailure() { console.warn('微信键盘状态暂时无法确认；页面仍可继续操作。'); }

export function useNavigationKeyboardHeight(): number {
  const [height, setHeight] = useState(0);
  const lifecycle = useRef<ReturnType<typeof createKeyboardHeightLifecycle> | null>(null);
  useEffect(() => {
    const current = createKeyboardHeightLifecycle(Taro, setHeight, reportKeyboardFailure);
    lifecycle.current = current;
    current.show();
    return () => { current.dispose(); lifecycle.current = null; };
  }, []);
  useDidShow(() => lifecycle.current?.show());
  useDidHide(() => lifecycle.current?.hide());
  return height;
}

/** Dismissal is best effort: a platform failure must not block navigation or an in-memory preview. */
export async function dismissKeyboard(): Promise<void> {
  try { await Taro.hideKeyboard(); } catch { reportKeyboardFailure(); }
}
