import { Children } from 'react';
import { Button, Text, type ButtonProps } from '@tarojs/components';
import { activateOnKey, type ActivationEvent } from './keyboard';

export interface AccessibleButtonProps extends Omit<ButtonProps, 'onClick'> {
  onClick?: () => void;
  role?: 'button' | 'switch';
  'aria-checked'?: boolean;
  'aria-pressed'?: boolean;
  'aria-current'?: 'page';
}

/** Taro H5 custom elements forward these attributes but do not supply keyboard activation. */
export function AccessibleButton({ onClick, role = 'button', disabled, children, ...props }: AccessibleButtonProps) {
  const semanticProps: ButtonProps & {
    role: 'button' | 'switch';
    tabindex: number;
    'aria-disabled': boolean;
    onKeyDown: (event: ActivationEvent) => void;
  } = {
    ...props,
    // A false boolean attribute on a custom element can still match Taro's [disabled] CSS.
    disabled: disabled ? true : undefined,
    role,
    tabindex: disabled ? -1 : 0,
    'aria-disabled': Boolean(disabled),
    onClick: () => { if (!disabled) onClick?.(); },
    onKeyDown: event => activateOnKey(event, onClick, disabled),
  };
  return <Button {...semanticProps}>{Children.map(children, child => typeof child === 'string' || typeof child === 'number' ? <Text className="sc-button-text">{child}</Text> : child)}</Button>;
}
