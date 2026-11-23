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

export interface RuleHelp { means: string; why: string; fix: string }

const HELP: Record<string, RuleHelp> = {
  EXTERNAL_LINK_REDIRECT: {
    means: "A page links to another website, and that address sends visitors on to a different address.",
    why: "It still works for visitors, but it is slower and the link can break later. If the same link is on every page it is almost always in the shared header, footer or menu, so one edit fixes them all.",
    fix: "Open the link in a browser, copy the address it ends up on, and use that final address in the link.",
  },
  EXTERNAL_LINK_BROKEN: {
    means: "A page links to another website and that address no longer works.",
    why: "Broken links frustrate visitors and look careless to search engines.",
    fix: "Replace the link with a working address, or remove it.",
  },
  TITLE_TOO_LONG: {
    means: "The page title is longer than search results usually show, so Google cuts the end off.",
    why: "A cut-off title can hide the words or the brand name you wanted people to see.",
    fix: "Shorten the title, keeping the main topic first. The Title repair tool on the Pages tab fixes the common case where the brand name appears twice.",
  },
  TITLE_TOO_SHORT: { means: "The page title is very short.", why: "A short title wastes space where you could describe the page.", fix: "Write a clearer title that says what the page is about." },
  HEADING_HIERARCHY_SKIP: {
    means: "The page jumps heading levels, for example from a main heading (H1) straight to an H3.",
    why: "Headings are an outline for readers and screen readers. A skipped level is a small accessibility and clarity issue, not a ranking problem.",
    fix: "Use the next level down (H2 after H1). If it comes from a theme element such as a sidebar or related-posts box, change the theme once.",
  },
  IMAGE_MISSING_DIMENSIONS: {
    means: "An image has no width and height set in the page code.",
    why: "The browser cannot reserve space for it, so the page can jump while loading, which hurts the layout-shift score.",
    fix: "Add width and height attributes (or set them in your theme or media settings).",
  },
  THIN_CONTENT: {
    means: "The page has little text compared with what is usual for its type.",
    why: "Very short pages give search engines little to understand. Contact pages and index pages are often short on purpose.",
    fix: "If the page should rank, add useful, original text. If it is a contact or listing page, you can leave it.",
  },
  PERFORMANCE_OPTIMIZATION_OPPORTUNITY: {
    means: "Google's PageSpeed test found something that could make the page load faster.",
    why: "Faster pages are nicer for visitors and help the page-experience signals.",
    fix: "Open the page's performance details to see the exact suggestions (for example image sizes or unused code).",
  },
  META_DESCRIPTION_MISSING: { means: "The page has no meta description.", why: "Google then picks text itself, which is often not the best summary.", fix: "Write a one or two sentence summary of the page." },
  TITLE_MISSING: { means: "The page has no title.", why: "The title is the main headline in search results.", fix: "Add a clear, specific title." },
};

export function ruleHelp(code: string): RuleHelp | null {
  return HELP[code] ?? null;
}
