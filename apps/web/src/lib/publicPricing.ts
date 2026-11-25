// The plans as offered to new buyers, read from the API without a login so the marketing pages never show a stale price.
// Failure, or no approved plan yet, shows "Pricing is being finalized" rather than a guessed number.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

export interface PublicPlan { code: string; name: string; description: string | null; interval: "month" | "year"; price_cents: number; currency: string; trial_days: number; monthly_equivalent_cents: number }
// `pricing_finalized` is false until the owner has approved at least one plan; until then no price is shown anywhere.
export interface PublicPricing { plans: PublicPlan[]; annual_saving_cents: number; pricing_finalized: boolean }

export async function getPublicPricing(): Promise<PublicPricing | null> {
  try {
    const res = await fetch(`${API_BASE_URL}/public/pricing`, { next: { revalidate: 300 } });
    if (!res.ok) return null;
    return (await res.json()) as PublicPricing;
  } catch {
    return null;
  }
}

export function money(cents: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency, minimumFractionDigits: cents % 100 === 0 ? 0 : 2 }).format(cents / 100);
  } catch {
    return `${(cents / 100).toFixed(2)} ${currency}`;
  }
}
