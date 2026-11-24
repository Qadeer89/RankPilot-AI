export default function JsonLd({ data }: { data: Record<string, unknown> }) {
  // Content is built from static strings on the server, so serialising it is safe; "<" is escaped to keep it inert inside a script tag.
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\\u003c") }} />;
}
