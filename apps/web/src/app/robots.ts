import type { MetadataRoute } from "next";
import { IS_INDEXABLE, SITE_URL } from "@/lib/site";

// Marketing pages are crawlable; the signed-in app and account screens are not. Non-production environments are closed entirely.
export default function robots(): MetadataRoute.Robots {
  if (!IS_INDEXABLE) return { rules: [{ userAgent: "*", disallow: "/" }] };
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/dashboard", "/login", "/register", "/forgot-password", "/reset-password", "/verify-email"] }],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
