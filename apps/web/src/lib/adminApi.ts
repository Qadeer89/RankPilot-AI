// Super Admin API client. The server decides who is allowed; nothing here is a security boundary.
import { request } from "@/lib/api";

export type Query = Record<string, string | number | boolean | undefined | null>;

export function qs(params: Query): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const text = sp.toString();
  return text ? `?${text}` : "";
}

export function adminGet<T>(token: string, path: string, params: Query = {}) {
  return request<T>(`/admin/${path}${qs(params)}`, { headers: { Authorization: `Bearer ${token}` } });
}

export function adminSend<T>(token: string, method: "POST" | "PUT" | "DELETE", path: string, body: unknown) {
  return request<T>(`/admin/${path}`, { method, headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(body) });
}

export type MoneyMap = Record<string, number>;

export interface Paged<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export function formatMoneyMap(map: MoneyMap | undefined | null): string {
  const entries = Object.entries(map ?? {});
  if (entries.length === 0) return "$0";
  return entries
    .map(([cur, cents]) =>
      new Intl.NumberFormat("en-US", { style: "currency", currency: cur, minimumFractionDigits: cents % 100 === 0 ? 0 : 2 }).format(cents / 100)
    )
    .join(" · ");
}
