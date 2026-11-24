// Where this frontend lives and whether search engines may index it. Both come from the environment so the
// same build artefact logic works on any domain; only production is ever indexable.
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3100").replace(/\/$/, "");
export const APP_ENV = process.env.NEXT_PUBLIC_APP_ENV ?? "development";
export const IS_INDEXABLE = APP_ENV === "production";

// Shown on the contact, privacy and terms pages. Set NEXT_PUBLIC_CONTACT_EMAIL to a mailbox that is actually read.
export const CONTACT_EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL ?? "hello@bugsnap-ai.com";
