"use client";

import { useCallback, useState } from "react";
import {
  ApiError,
  ChatMessage,
  askAssistant,
  submitChatFeedback,
} from "@/lib/api";

let localIdCounter = 0;

export function useAssistantChat(token: string | null, organizationId: string | null) {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = useCallback(() => {
    setConversationId(null);
    setMessages([]);
    setError(null);
  }, []);

  const loadConversation = useCallback((id: string | null, history: ChatMessage[]) => {
    setConversationId(id);
    setMessages(history);
    setError(null);
  }, []);

  const send = useCallback(
    async (question: string, context?: Record<string, unknown>) => {
      if (!token || !organizationId || !question.trim()) return;
      setError(null);

      const optimisticUser: ChatMessage = {
        id: `local-${localIdCounter++}`,
        conversation_id: conversationId ?? "pending",
        role: "user",
        content: question,
        sources: [],
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimisticUser]);
      setSending(true);

      try {
        const assistantMessage = await askAssistant(token, organizationId, question, conversationId, context);
        setConversationId(assistantMessage.conversation_id);
        setMessages((prev) => [...prev, assistantMessage]);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "The assistant couldn't respond. Please try again.");
      } finally {
        setSending(false);
      }
    },
    [token, organizationId, conversationId]
  );

  const sendFeedback = useCallback(
    async (messageId: string, rating: "up" | "down") => {
      if (!token || !organizationId || messageId.startsWith("local-")) return;
      try {
        await submitChatFeedback(token, organizationId, messageId, rating);
      } catch {
        // Feedback is best-effort -- a failed submit shouldn't disrupt the conversation.
      }
    },
    [token, organizationId]
  );

  return { conversationId, messages, sending, error, send, sendFeedback, reset, loadConversation };
}
