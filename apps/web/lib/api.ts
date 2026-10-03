import { ApiError } from './errors';

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface FetchOptions extends RequestInit {
  requireOwner?: boolean;
}

export async function fetchApi<T>(path: string, options?: FetchOptions): Promise<T> {
  const headers = new Headers(options?.headers);
  if (options?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  const token = typeof window !== "undefined" ? sessionStorage.getItem("ownerToken") : null;
  if (options?.requireOwner && !token) {
    throw new Error("Owner token is required for this action. Please configure it in Settings.");
  }
  if (token) headers.set("x-owner-token", token);

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    let errorText = await res.text();
    try {
      const parsed = JSON.parse(errorText);
      if (parsed.detail) errorText = typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail);
    } catch {
      // ignore
    }
    throw new ApiError(res.status, `API Error ${res.status}: ${errorText}`);
  }
  return res.json() as Promise<T>;
}
