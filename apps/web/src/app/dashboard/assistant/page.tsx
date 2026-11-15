"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ApiError,
  ChatConversation,
  MeResponse,
  getMe,
  listChatConversations,
  listChatMessages,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import MessageList from "@/components/chat/MessageList";
import ChatComposer from "@/components/chat/ChatComposer";
import { useAssistantChat } from "@/components/chat/useAssistantChat";
import styles from "./assistant.module.css";

function AssistantPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [error, setError] = useState<string | null>(null);

  const organizationId = me?.organizations[0]?.id ?? null;
  const token = getToken();
  const { conversationId, messages, sending, error: chatError, send, sendFeedback, reset, loadConversation } =
    useAssistantChat(token, organizationId);

  const refreshConversations = useCallback(
    async (activeToken: string, orgId: string) => {
      const list = await listChatConversations(activeToken, orgId);
      setConversations(list);
      return list;
    },
    []
  );

  useEffect(() => {
    const activeToken = getToken();
    if (!activeToken) {
      router.push("/login");
      return;
    }
    getMe(activeToken)
      .then(async (meResponse) => {
        setMe(meResponse);
        const orgId = meResponse.organizations[0]?.id;
        if (!orgId) return;
        await refreshConversations(activeToken, orgId);

        const preselect = searchParams.get("conversation");
        if (preselect) {
          const history = await listChatMessages(activeToken, orgId, preselect);
          loadConversation(preselect, history);
        }
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "Failed to load the assistant.");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  async function handleSelectConversation(id: string) {
    if (!token || !organizationId) return;
    const history = await listChatMessages(token, organizationId, id);
    loadConversation(id, history);
  }

  async function handleSend(question: string) {
    await send(question);
    if (token && organizationId) {
      await refreshConversations(token, organizationId);
    }
  }

  function handleNewChat() {
    reset();
  }

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <div className={styles.header}>
          <h1>AI Assistant</h1>
          <p>Ask about setup, connectors, automation modes, and anything else in RankPilot AI.</p>
        </div>

        {error && <p role="alert">{error}</p>}

        <div className={styles.body}>
          <div className={styles.sidebar}>
            <button type="button" className={styles.newChatButton} onClick={handleNewChat}>
              + New chat
            </button>
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                className={`${styles.conversationItem} ${
                  conversation.id === conversationId ? styles.conversationItemActive : ""
                }`}
                onClick={() => handleSelectConversation(conversation.id)}
              >
                {conversation.title}
              </button>
            ))}
          </div>

          <div className={styles.chatCard}>
            <div className={styles.messages}>
              <MessageList messages={messages} sending={sending} error={chatError} onFeedback={sendFeedback} />
            </div>
            <ChatComposer onSend={handleSend} disabled={sending} />
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AssistantPage() {
  return (
    <Suspense fallback={null}>
      <AssistantPageInner />
    </Suspense>
  );
}
