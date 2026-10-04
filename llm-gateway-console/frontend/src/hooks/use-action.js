import { useRef, useState } from 'react';

export function useAction() {
  const locked = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function run(action) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError('');
    try { await action(); }
    catch (failure) { setError(failure.message || 'The operation failed. Please retry.'); }
    finally { locked.current = false; setBusy(false); }
  }
  return { busy, error, run };
}
