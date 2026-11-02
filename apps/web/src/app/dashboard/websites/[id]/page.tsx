import { Suspense } from "react";
import WebsiteDetailClient from "./website-detail-client";

// This route is entirely client-rendered (auth from localStorage, data
// fetched from the API at runtime), so it can't be part of the static
// shell. `instant` is a route-segment config export, which only a Server
// Component file can provide — hence this thin wrapper around the actual
// "use client" page. The Suspense boundary is required because the client
// page reads URL data (useParams) that isn't available during prerendering.
export const instant = false;

export default function WebsiteDetailPage() {
  return (
    <Suspense fallback={<p style={{ padding: 32 }}>Loading...</p>}>
      <WebsiteDetailClient />
    </Suspense>
  );
}
