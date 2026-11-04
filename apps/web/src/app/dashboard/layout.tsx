import { Suspense } from "react";
import AppShell from "@/components/AppShell";

// AppShell is a client component that reads the current route
// (usePathname) to highlight sidebar navigation, which Next.js can't
// prerender statically -- the Suspense boundary is required so the
// dashboard shell renders on the client without blocking the build
// (mirrors the same pattern the website detail page already uses).
export const instant = false;

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={null}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
