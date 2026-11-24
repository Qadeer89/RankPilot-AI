import { ImageResponse } from "next/og";

export const alt = "RankPilot AI: AI-powered SEO audit, recommendations and progress tracking";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "center", padding: 80, background: "linear-gradient(180deg,#111b3a,#1a2550)", color: "#fff" }}>
        <div style={{ fontSize: 40, fontWeight: 800, display: "flex" }}>RankPilot <span style={{ color: "#b7f36b", marginLeft: 12 }}>AI</span></div>
        <div style={{ fontSize: 68, fontWeight: 800, lineHeight: 1.05, marginTop: 28, maxWidth: 980 }}>Turn SEO insights into measurable growth.</div>
        <div style={{ fontSize: 30, color: "#c8cee6", marginTop: 28 }}>Audit. Discover. Approve. Verify. Track.</div>
      </div>
    ),
    size,
  );
}
