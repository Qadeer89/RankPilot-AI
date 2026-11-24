import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { IS_INDEXABLE, SITE_URL } from "@/lib/site";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  robots: IS_INDEXABLE ? { index: true, follow: true } : { index: false, follow: false },
  applicationName: "RankPilot AI",
  title: { default: "RankPilot AI", template: "%s | RankPilot AI" },
  description: "AI-powered SEO audit, recommendations and progress tracking for your website.",
  openGraph: { siteName: "RankPilot AI", type: "website", locale: "en_US" },
  twitter: { card: "summary_large_image" },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
