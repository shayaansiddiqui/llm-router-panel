function trimTrailingSlash(value) {
  return value.replace(/\/+$/, '');
}

const defaultApiBaseUrl = import.meta.env.DEV ? 'http://localhost:8000' : window.location.origin;

export const API_BASE_URL = trimTrailingSlash(import.meta.env.VITE_API_BASE_URL || defaultApiBaseUrl);
export const PUBLIC_GATEWAY_URL = trimTrailingSlash(import.meta.env.VITE_PUBLIC_GATEWAY_URL || 'https://ai.gettingstarted.app');

export async function api(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });

  if (!response.ok) {
    const text = await response.text();
    let message = text || `Request failed with ${response.status}`;
    try {
      const payload = JSON.parse(text);
      message = payload.detail || message;
    } catch {
      message = text || message;
    }
    throw new Error(message);
  }

  return response.json();
}
