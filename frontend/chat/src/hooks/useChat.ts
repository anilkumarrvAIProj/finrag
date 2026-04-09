import { useState, useCallback, useRef } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:7200';

export interface Citation {
  ref: number;
  filename: string;
  page_start?: number;
  page_end?: number;
  section_title?: string;
  document_id?: string;
}

export interface WebSource {
  ref: number;
  title: string;
  url: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  web_sources?: WebSource[];
  intent?: string;
  latency_ms?: number;
  web_search_used?: boolean;
  streaming?: boolean;
}

export interface UseChatOptions {
  sessionId?: string;
  docIds?: string[];
  docTypeFilter?: string;
  enableWebSearch?: boolean;
  outputFormat?: 'paragraph' | 'bullets' | 'table';
}

export function useChat(options: UseChatOptions = {}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [status, setStatus] = useState<string>('');
  const [sessionId, setSessionId] = useState<string | undefined>(options.sessionId);
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(async (query: string) => {
    if (isStreaming) return;

    // Add user message
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: query,
    };
    setMessages(prev => [...prev, userMsg]);

    // Add placeholder assistant message
    const assistantId = crypto.randomUUID();
    setMessages(prev => [
      ...prev,
      { id: assistantId, role: 'assistant', content: '', streaming: true },
    ]);

    setIsStreaming(true);
    setStatus('Searching documents…');

    abortRef.current = new AbortController();
    const token = localStorage.getItem('finrag_token');

    try {
      const resp = await fetch(`${API_BASE}/api/v1/chat/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          query,
          session_id: sessionId || undefined,
          doc_ids: options.docIds,
          doc_type_filter: options.docTypeFilter,
          enable_web_search: options.enableWebSearch ?? false,
          output_format: options.outputFormat ?? 'paragraph',
        }),
        signal: abortRef.current.signal,
      });

      // Capture session id from response header
      const sid = resp.headers.get('X-Session-ID');
      if (sid) setSessionId(sid);

      const reader = resp.body?.getReader();
      if (!reader) throw new Error('No response body');

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
          const data = JSON.parse(dataLine.slice(5).trim());

          switch (event) {
            case 'status':
              setStatus(data.message);
              break;

            case 'retrieval_complete':
              setStatus(`Found ${data.chunks_found} relevant chunks (${data.intent})`);
              setMessages(prev => prev.map(m =>
                m.id === assistantId
                  ? { ...m, intent: data.intent }
                  : m
              ));
              break;

            case 'token':
              setMessages(prev => prev.map(m =>
                m.id === assistantId
                  ? { ...m, content: m.content + data.text }
                  : m
              ));
              break;

            case 'done':
              setMessages(prev => prev.map(m =>
                m.id === assistantId
                  ? {
                      ...m,
                      content: data.full_response,
                      citations: data.citations,
                      web_sources: data.web_sources,
                      web_search_used: data.web_search_used,
                      latency_ms: data.latency_ms,
                      streaming: false,
                    }
                  : m
              ));
              setStatus('');
              break;

            case 'error':
              setMessages(prev => prev.map(m =>
                m.id === assistantId
                  ? { ...m, content: `Error: ${data.message}`, streaming: false }
                  : m
              ));
              setStatus('');
              break;
          }
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') return;
      setMessages(prev => prev.map(m =>
        m.id === assistantId
          ? { ...m, content: 'Connection error. Please try again.', streaming: false }
          : m
      ));
    } finally {
      setIsStreaming(false);
      setStatus('');
    }
  }, [isStreaming, sessionId, options]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setStatus('');
    // Mark last assistant message as done
    setMessages(prev => prev.map((m, i) =>
      i === prev.length - 1 && m.role === 'assistant' ? { ...m, streaming: false } : m
    ));
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setSessionId(undefined);
  }, []);

  return { messages, isStreaming, status, sessionId, sendMessage, stop, clearMessages };
}
