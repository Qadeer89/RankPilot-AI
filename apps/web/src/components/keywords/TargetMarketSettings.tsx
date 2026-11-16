"use client";

import { useState } from "react";
import { ApiError, CountryOption, Website, updateWebsiteSettings } from "@/lib/api";
import styles from "@/app/dashboard/websites/[id]/keywords/keywords.module.css";

interface Props {
  token: string;
  organizationId: string;
  website: Website;
  countries: CountryOption[];
  onSaved: (website: Website) => void;
}

// ISO 639-1 languages offered per market. Free text is not accepted so a
// saved value is always one the backend recognises.
const LANGUAGES: { code: string; name: string }[] = [
  { code: "en", name: "English" }, { code: "ur", name: "Urdu" }, { code: "es", name: "Spanish" },
  { code: "fr", name: "French" }, { code: "de", name: "German" }, { code: "ar", name: "Arabic" },
  { code: "hi", name: "Hindi" }, { code: "pt", name: "Portuguese" }, { code: "it", name: "Italian" },
  { code: "nl", name: "Dutch" }, { code: "tr", name: "Turkish" }, { code: "id", name: "Indonesian" },
];

export default function TargetMarketSettings({ token, organizationId, website, countries, onSaved }: Props) {
  const [primary, setPrimary] = useState(website.target_country ?? "");
  const [additional, setAdditional] = useState<string[]>(website.additional_target_countries);
  const [languages, setLanguages] = useState<Record<string, string>>(website.target_languages_by_country ?? {});
  const [defaultLanguage, setDefaultLanguage] = useState(website.target_language ?? "");
  const [city, setCity] = useState(website.target_city ?? "");
  const [toAdd, setToAdd] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const nameOf = (code: string) => countries.find((c) => c.code === code)?.name ?? code;
  const markets = [...(primary ? [primary] : []), ...additional.filter((c) => c !== primary)];

  function addCountry() {
    if (!toAdd || toAdd === primary || additional.includes(toAdd)) return;
    setAdditional([...additional, toAdd]);
    setToAdd("");
    setSaved(false);
  }

  function removeCountry(code: string) {
    setAdditional(additional.filter((c) => c !== code));
    const next = { ...languages };
    delete next[code];
    setLanguages(next);
    setSaved(false);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await updateWebsiteSettings(token, organizationId, website.id, {
        target_country: primary,
        additional_target_countries: additional.filter((c) => c !== primary),
        target_language: defaultLanguage,
        target_city: city.trim(),
        target_languages_by_country: Object.fromEntries(
          Object.entries(languages).filter(([code, lang]) => lang && markets.includes(code))
        ),
      });
      onSaved(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save target market settings.");
    } finally {
      setSaving(false);
    }
  }

  if (countries.length === 0) {
    return <p className={styles.empty}>Loading countries…</p>;
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Target market settings" className={styles.targetForm}>
      <strong>Target market</strong>
      <p className={styles.subtitle}>
        The primary country pre-selects every Keyword Intelligence view. Add other countries you want to rank in.
      </p>

      <div className={styles.formRow}>
        <label htmlFor="tm-primary">Primary country</label>
        <select
          id="tm-primary"
          className={styles.select}
          value={primary}
          onChange={(e) => { setPrimary(e.target.value); setSaved(false); }}
        >
          <option value="">Not set</option>
          {countries.map((c) => (
            <option key={c.code} value={c.code}>{c.name} ({c.code})</option>
          ))}
        </select>
        <label htmlFor="tm-city">City / region (optional)</label>
        <input id="tm-city" className={styles.input} value={city} maxLength={128}
          onChange={(e) => { setCity(e.target.value); setSaved(false); }} />
        <label htmlFor="tm-lang">Default language</label>
        <select id="tm-lang" className={styles.select} value={defaultLanguage}
          onChange={(e) => { setDefaultLanguage(e.target.value); setSaved(false); }}>
          <option value="">Not set</option>
          {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
        </select>
      </div>

      <div className={styles.formRow}>
        <label htmlFor="tm-add">Additional countries</label>
        <select id="tm-add" className={styles.select} value={toAdd} onChange={(e) => setToAdd(e.target.value)}>
          <option value="">Choose a country…</option>
          {countries.filter((c) => c.code !== primary && !additional.includes(c.code)).map((c) => (
            <option key={c.code} value={c.code}>{c.name} ({c.code})</option>
          ))}
        </select>
        <button type="button" className={styles.secondaryButton} onClick={addCountry} disabled={!toAdd}>Add country</button>
      </div>

      {markets.length > 0 && (
        <table className={styles.table}>
          <thead><tr><th>Market</th><th>Language for this market</th><th /></tr></thead>
          <tbody>
            {markets.map((code) => (
              <tr key={code}>
                <td>{nameOf(code)} ({code}){code === primary ? " — primary" : ""}</td>
                <td>
                  <select
                    className={styles.select}
                    aria-label={`Language for ${nameOf(code)}`}
                    value={languages[code] ?? ""}
                    onChange={(e) => { setLanguages({ ...languages, [code]: e.target.value }); setSaved(false); }}
                  >
                    <option value="">Use default</option>
                    {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
                  </select>
                </td>
                <td>
                  {code !== primary && (
                    <button type="button" className={styles.secondaryButton} onClick={() => removeCountry(code)}
                      aria-label={`Remove ${nameOf(code)}`}>Remove</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className={styles.formRow}>
        <button type="submit" className={styles.primaryButton} disabled={saving}>
          {saving ? "Saving…" : "Save target market"}
        </button>
        {saved && <span role="status" className={styles.freshnessNote}>Saved.</span>}
      </div>
      {error && <p className={styles.error} role="alert">{error}</p>}
    </form>
  );
}
