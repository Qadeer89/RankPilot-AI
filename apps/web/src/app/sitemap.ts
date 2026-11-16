import type { MetadataRoute } from "next";
import { IS_INDEXABLE, SITE_URL } from "@/lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  if (!IS_INDEXABLE) return [];
  return ["/", "/login", "/register"].map((path) => ({ url: `${SITE_URL}${path}` }));
}
