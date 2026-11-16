// Display helpers for the billing screens. Money is always integer cents.

export function formatMoney(cents: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency, minimumFractionDigits: cents % 100 === 0 ? 0 : 2 }).format(
    cents / 100
  );
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function planLabel(interval: "month" | "year"): string {
  return interval === "month" ? "Monthly" : "Annual";
}

export function priceLine(cents: number, currency: string, interval: "month" | "year"): string {
  return `${formatMoney(cents, currency)} / ${interval === "month" ? "month" : "year"}`;
}

export const STATUS_LABEL: Record<string, string> = {
  trialing: "Free trial",
  active: "Active",
  past_due: "Payment past due",
  unpaid: "Unpaid",
  paused: "Paused",
  cancelled: "Cancelled",
  expired: "Expired",
  refunded: "Refunded",
};

export function statusTone(status: string | undefined, entitled: boolean): "good" | "warn" | "bad" | "neutral" {
  if (!status) return "neutral";
  if (["active", "trialing"].includes(status)) return "good";
  if (status === "cancelled" && entitled) return "warn";
  if (status === "past_due" && entitled) return "warn";
  return "bad";
}
