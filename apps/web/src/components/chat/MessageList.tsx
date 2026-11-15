"use client";

import { useState } from "react";
import Link from "next/link";
import { ChatMessage } from "@/lib/api";
import styles from "./MessageList.module.css";

export default function MessageList({
  messages,
  sending,
  error,
  onFeedback,
}: {
  messages: ChatMessage[];
  sending: boolean;
  error: string | null;
  onFeedback: (messageId: string, rating: "up" | "down") => void;
}) {
  const [feedbackGiven, setFeedbackGiven] = useState<Record<string, "up" | "down">>({});

  function handleFeedback(messageId: string, rating: "up" | "down") {
    setFeedbackGiven((prev) => ({ ...prev, [messageId]: rating }));
    onFeedback(messageId, rating);
  }

  if (messages.length === 0 && !sending) {
    return (
      <div className={styles.empty}>
        Ask me anything about setting up or using RankPilot AI -- connecting a website, running audits,
        automation modes, and more.
      </div>
    );
  }

  return (
    <div className={styles.list}>
      {messages.map((message) => {
        if (message.role === "user") {
          return (
            <div key={message.id} className={`${styles.row} ${styles.rowUser}`}>
              <div className={`${styles.bubble} ${styles.bubbleUser}`}>{message.content}</div>
            </div>
          );
        }

        const given = feedbackGiven[message.id];
        return (
          <div key={message.id} className={`${styles.row} ${styles.rowAssistant}`}>
            <div className={styles.assistantColumn}>
              <div className={`${styles.bubble} ${styles.bubbleAssistant}`}>{message.content}</div>
              {message.sources.length > 0 && (
                <div className={styles.sources}>
                  {message.sources.map((source) => (
                    <Link key={source.document_id} href={source.suggested_path} className={styles.sourceChip}>
                      {source.title}
                    </Link>
                  ))}
                </div>
              )}
              {!message.id.startsWith("local-") && (
                <div className={styles.feedbackRow}>
                  <button
                    type="button"
                    className={`${styles.feedbackButton} ${given === "up" ? styles.feedbackButtonActive : ""}`}
                    aria-label="Helpful"
                    onClick={() => handleFeedback(message.id, "up")}
                  >
                    👍
                  </button>
                  <button
                    type="button"
                    className={`${styles.feedbackButton} ${given === "down" ? styles.feedbackButtonActive : ""}`}
                    aria-label="Not helpful"
                    onClick={() => handleFeedback(message.id, "down")}
                  >
                    👎
                  </button>
                </div>
              )}
            </div>
          </div>
        );
      })}

      {sending && (
        <div className={`${styles.row} ${styles.rowAssistant}`}>
          <div className={styles.thinking} aria-label="Assistant is responding">
            <span className={styles.thinkingDot} />
            <span className={styles.thinkingDot} />
            <span className={styles.thinkingDot} />
          </div>
        </div>
      )}

      {error && <p className={styles.error} role="alert">{error}</p>}
    </div>
  );
}
