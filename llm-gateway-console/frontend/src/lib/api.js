function trimTrailingSlash(value) {
  return value.replace(/\/+$/, '');
}

const defaultApiBaseUrl = import.meta.env.DEV ? 'http://localhost:8000' : window.location.origin;
const ADMIN_TOKEN_KEY = 'llm_gateway_admin_token';

export const API_BASE_URL = trimTrailingSlash(import.meta.env.VITE_API_BASE_URL || defaultApiBaseUrl);
export const PUBLIC_GATEWAY_URL = trimTrailingSlash(import.meta.env.VITE_PUBLIC_GATEWAY_URL || 'https://ai.gettingstarted.app');

export function getAdminToken() {
  return window.localStorage.getItem(ADMIN_TOKEN_KEY);
}

export function setAdminToken(token) {
  window.localStorage.setItem(ADMIN_TOKEN_KEY, token);
}

export function clearAdminToken() {
  window.localStorage.removeItem(ADMIN_TOKEN_KEY);
}

export async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  const adminToken = getAdminToken();
  if (path.startsWith('/api/') && path !== '/api/auth/login' && adminToken && !headers.Authorization) {
    headers.Authorization = `Bearer ${adminToken}`;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers,
    ...options,
  });

  if (!response.ok) {
    if (response.status === 401 && path !== '/api/auth/login') {
      clearAdminToken();
    }
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
