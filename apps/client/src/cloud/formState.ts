import { useEffect, useRef, useState } from 'react';

export interface FormScope { authEpoch: number; selectedId: string | null }
interface FormOwner extends FormScope { generation: number }
interface ScopedForm<T> { owner: FormOwner; values: T }
const sameScope = (left: FormScope, right: FormScope) => left.authEpoch === right.authEpoch && left.selectedId === right.selectedId;
const sameOwner = (left: FormOwner, right: FormOwner) => sameScope(left, right) && left.generation === right.generation;

/** Cached pages mask another scope's fields synchronously, before passive effects run. */
export function useScopedForm<T>(scope: FormScope, runtimeScope: () => FormScope, empty: () => T) {
  const ownerRef = useRef<FormOwner>({ ...scope, generation: 0 });
  if (!sameScope(ownerRef.current, scope)) ownerRef.current = { ...scope, generation: ownerRef.current.generation + 1 };
  const owner = ownerRef.current;
  const [stored, setStored] = useState<ScopedForm<T>>(() => ({ owner, values: empty() }));
  const versionRef = useRef(0);
  const forOwner = (form: ScopedForm<T>): ScopedForm<T> => sameOwner(form.owner, owner) ? form : { owner, values: empty() };
  const isCurrent = () => sameOwner(ownerRef.current, owner) && sameScope(runtimeScope(), owner);
  const values = forOwner(stored).values;
  useEffect(() => {
    // An effect queued under an older render must not restore its scope later.
    setStored(current => isCurrent() ? forOwner(current) : current);
  }, [owner.authEpoch, owner.selectedId, owner.generation]);
  function update(transform: (current: T) => T): void {
    if (!isCurrent()) return;
    ++versionRef.current;
    setStored(current => isCurrent() ? { owner, values: transform(forOwner(current).values) } : current);
  }
  function complete(version: number, transform: (current: T) => T): void {
    if (isCurrent() && versionRef.current === version) update(transform);
  }
  return { values, isCurrent, update, complete, version: () => versionRef.current };
}
