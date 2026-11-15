"use client";

import { useState } from "react";
import styles from "./ChatComposer.module.css";

export default function ChatComposer({
  onSend,
  disabled,
}: {
  onSend: (question: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = useState("");

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <input
        type="text"
        className={styles.input}
        placeholder="Ask about setup, connectors, automation..."
        aria-label="Ask the assistant"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={disabled}
      />
      <button type="submit" className={styles.send} disabled={disabled || !value.trim()}>
        Send
      </button>
    </form>
  );
}
