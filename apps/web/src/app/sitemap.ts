import type { MetadataRoute } from "next";
import { IS_INDEXABLE, SITE_URL } from "@/lib/site";

const PAGES: { path: string; priority: number }[] = [
  { path: "/", priority: 1 }, { path: "/features", priority: 0.9 }, { path: "/how-it-works", priority: 0.8 }, { path: "/pricing", priority: 0.9 },
  { path: "/faq", priority: 0.6 }, { path: "/about", priority: 0.5 }, { path: "/contact", priority: 0.4 }, { path: "/privacy", priority: 0.3 }, { path: "/terms", priority: 0.3 },
];

// Only the production site invites search engines in; staging and development publish an empty sitemap.
export default function sitemap(): MetadataRoute.Sitemap {
  if (!IS_INDEXABLE) return [];
  return PAGES.map((p) => ({ url: `${SITE_URL}${p.path === "/" ? "" : p.path}`, priority: p.priority, changeFrequency: "monthly" as const }));
}
