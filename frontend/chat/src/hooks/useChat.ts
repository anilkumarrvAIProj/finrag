import { useState, useCallback, useRef } from 'react';
import axios from 'axios';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:7200';

export interface Citation {
  ref: number;
  filename: string;
  page_start?: number;
  page_end?: number;
  section_title?: string;
  relevance_score?: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  web_sources?: any[];
  web_search_used?: boolean;
  latency_ms?: number;
  streaming?: boolean;
  intent?: string;
}

export interface ChatSession {
  id: string;
  title: string;
  last_active_at?: string;
  fund_id?: string;
}

function getHeaders() {
  const token = localStorage.getItem('finrag_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [status, setStatus] = useState('');
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [quickQuestions, setQuickQuestions] = useState<string[]>([
    "What are the top 5 positions?",
    "What is the 1yr performance vs benchmark?",
    "What are the management and performance fees?",
    "What is the current AUM and liquidity terms?",
  ]);
  const abortRef = useRef<AbortController | null>(null);

  const loadSessions = useCallback(async () => {
    try {
      const res = await axios.get(`${BASE}/api/v1/chat/sessions`, { headers: getHeaders() });
      setSessions(res.data);
    } catch { }
  }, []);

  const loadSession = useCallback(async (sid: string) => {
    try {
      const res = await axios.get(`${BASE}/api/v1/chat/sessions/${sid}/messages`, { headers: getHeaders() });
      setSessionId(sid);
      setMessages(res.data.messages.map((m: any) => ({ ...m, streaming: false })));
    } catch { }
  }, []);

  const loadQuickQuestions = useCallback(async (fundId?: string) => {
    try {
      const url = fundId
        ? `${BASE}/api/v1/chat/quick-questions?fund_id=${fundId}`
        : `${BASE}/api/v1/chat/quick-questions`;
      const res = await axios.get(url, { headers: getHeaders() });
      setQuickQuestions(res.data.questions || []);
    } catch { }
  }, []);

  const newSession = useCallback(() => {
    setSessionId(undefined);
    setMessages([]);
    setStatus('');
  }, []);

  const deleteSession = useCallback(async (sid: string) => {
    try {
      await axios.delete(`${BASE}/api/v1/chat/sessions/${sid}`, { headers: getHeaders() });
      setSessions(prev => prev.filter(s => s.id !== sid));
      if (sessionId === sid) newSession();
    } catch { }
  }, [sessionId, newSession]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setStatus('');
  }, []);

  const sendMessage = useCallback(async (query: string, opts: {
    docIds?: string[];
    enableWebSearch?: boolean;
    fundId?: string;
    outputFormat?: string;
  } = {}) => {
    if (!query.trim() || isStreaming) return;

    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: 'user', content: query };
    const assistantId = crypto.randomUUID();
    const assistantMsg: ChatMessage = { id: assistantId, role: 'assistant', content: '', streaming: true };

    setMessages(prev => [...prev, userMsg, assistantMsg]);
    setIsStreaming(true);
    setStatus('');

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const body: any = {
        query,
        session_id: sessionId || undefined,
        enable_web_search: opts.enableWebSearch || false,
        output_format: opts.outputFormat || 'paragraph',
      };
      if (opts.docIds?.length) body.doc_ids = opts.docIds;
      if (opts.fundId) body.fund_id = opts.fundId;

      const res = await fetch(`${BASE}/api/v1/chat/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getHeaders() },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() ?? '';

        for (const raw of events) {
          if (!raw.trim()) continue;
          const lines = raw.split('\n');
          const eventLine = lines.find(l => l.startsWith('event:'));
          const dataLine = lines.find(l => l.startsWith('data:'));
          if (!eventLine || !dataLine) continue;

          const event = eventLine.slice(7).trim();
          const rawData = dataLine.slice(5).trim();
          if (!rawData) continue;

          try {
            const data = JSON.parse(rawData);
            switch (event) {
              case 'status':
                setStatus(data.message);
                break;
              case 'retrieval_complete':
                setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, intent: data.intent } : m));
                break;
              case 'token':
                setMessages(prev => prev.map(m =>
                  m.id === assistantId ? { ...m, content: m.content + data.text } : m
                ));
                break;
              case 'done':
                if (!sessionId && data.session_id) {
                  setSessionId(data.session_id);
                  loadSessions();
                }
                setMessages(prev => prev.map(m =>
                  m.id === assistantId ? {
                    ...m,
                    content: data.full_response || m.content,
                    citations: data.citations,
                    web_sources: data.web_sources,
                    web_search_used: data.web_search_used,
                    latency_ms: data.latency_ms,
                    streaming: false,
                  } : m
                ));
                setStatus('');
                break;
              case 'error':
                setMessages(prev => prev.map(m =>
                  m.id === assistantId ? { ...m, content: `Error: ${data.message}`, streaming: false } : m
                ));
                setStatus('');
                break;
            }
          } catch { }
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setMessages(prev => prev.map(m =>
          m.id === assistantId ? { ...m, content: 'Connection error. Please try again.', streaming: false } : m
        ));
      }
    } finally {
      setIsStreaming(false);
      setStatus('');
      setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, streaming: false } : m));
    }
  }, [isStreaming, sessionId, loadSessions]);

  return {
    messages, sessions, isStreaming, status, sessionId,
    quickQuestions, sendMessage, stop, newSession,
    loadSessions, loadSession, loadQuickQuestions, deleteSession,
  };
}
