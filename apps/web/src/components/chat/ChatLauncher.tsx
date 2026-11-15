"use client";

import { useState } from "react";
import Link from "next/link";
import { getToken } from "@/lib/auth";
import MessageList from "./MessageList";
import ChatComposer from "./ChatComposer";
import { useAssistantChat } from "./useAssistantChat";
import styles from "./ChatLauncher.module.css";

/** Part 5: "dedicated page + floating launcher". The launcher opens a
 * compact version of the same conversation; "Open full view" hands off
 * to /dashboard/assistant without losing the thread.
 */
export default function ChatLauncher({ organizationId }: { organizationId: string | null }) {
  const [open, setOpen] = useState(false);
  const token = getToken();
  const { messages, sending, error, send, sendFeedback, conversationId } = useAssistantChat(token, organizationId);

  if (!organizationId) return null;

  return (
    <>
      {open && (
        <div className={styles.panel} role="dialog" aria-label="RankPilot AI Assistant">
          <div className={styles.header}>
            <span className={styles.headerTitle}>RankPilot Assistant</span>
            <div className={styles.headerActions}>
              <Link
                href={conversationId ? `/dashboard/assistant?conversation=${conversationId}` : "/dashboard/assistant"}
                className={styles.headerLink}
                onClick={() => setOpen(false)}
              >
                Open full view
              </Link>
              <button type="button" className={styles.closeButton} aria-label="Close assistant" onClick={() => setOpen(false)}>
                ×
              </button>
            </div>
          </div>
          <div className={styles.body}>
            <MessageList messages={messages} sending={sending} error={error} onFeedback={sendFeedback} />
          </div>
          <div className={styles.footer}>
            <ChatComposer onSend={send} disabled={sending} />
          </div>
        </div>
      )}
      <button
        type="button"
        className={styles.launcher}
        aria-label={open ? "Close RankPilot Assistant" : "Open RankPilot Assistant"}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "×" : "💬"}
      </button>
    </>
  );
}
