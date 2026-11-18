/** Plain-language names for crawl rule codes. Unknown codes fall back to a readable form of the code itself. */
const LABELS: Record<string, string> = {
  HEADING_HIERARCHY_SKIP: "Heading levels skipped (for example H2 straight to H4)",
  EXTERNAL_LINK_REDIRECT: "A link to another site redirects",
  TITLE_TOO_LONG: "Page title is long enough to be cut off in search results",
  TITLE_TOO_SHORT: "Page title is very short",
  TITLE_MISSING: "Page has no title",
  META_DESCRIPTION_MISSING: "Page has no meta description",
  META_DESCRIPTION_TOO_LONG: "Meta description is too long",
  IMAGE_MISSING_DIMENSIONS: "Image has no width and height set",
  IMAGE_ALT_MISSING: "Image has no alt text",
  CANONICAL_MISSING: "Page has no canonical tag",
  H1_MISSING: "Page has no main heading (H1)",
  H1_MULTIPLE: "Page has more than one main heading (H1)",
  NOINDEX_DIRECTIVE: "Page tells search engines not to index it",
  STRUCTURED_DATA_MISSING: "Page has no structured data",
};

export function ruleLabel(code: string): string {
  if (LABELS[code]) return LABELS[code];
  const words = code.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
