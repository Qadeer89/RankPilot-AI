import type { MetadataRoute } from "next";
import { IS_INDEXABLE, SITE_URL } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  if (!IS_INDEXABLE) {
    return { rules: { userAgent: "*", disallow: "/" } };
  }
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/dashboard", "/reset-password", "/verify-email"] },
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
