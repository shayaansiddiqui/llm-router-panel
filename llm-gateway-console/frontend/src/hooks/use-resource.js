import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

// Cancel superseded reads so an older refresh cannot replace newer data.
export function useResource(path, refreshKey) {
  const [state, setState] = useState({ data: null, loading: true, error: '' });
  useEffect(() => {
    const controller = new AbortController();
    setState((previous) => ({ ...previous, loading: true, error: '' }));
    api(path, { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setState({ data, loading: false, error: '' }); })
      .catch((error) => { if (!controller.signal.aborted) setState({ data: null, loading: false, error: error.message }); });
    return () => controller.abort();
  }, [path, refreshKey]);
  return state;
}
