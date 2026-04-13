import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useChat, ChatMessage, Citation } from '../hooks/useChat';
import {
  Send, Square, Plus, Trash2, FileText,
  ExternalLink, ChevronDown, ChevronRight, Globe,
} from 'lucide-react';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:7200';

function CitationPanel({ citations, webSources }: { citations?: Citation[]; webSources?: any[] }) {
  const [open, setOpen] = useState(false);
  const filtered = citations?.filter(c => {
    const score = c.relevance_score;
    return score === undefined || score === null || score > 0;
  });
  const total = (filtered?.length ?? 0) + (webSources?.length ?? 0);
  if (!total) return null;

  return (
    <div style={{ marginTop: 8, border: '0.5px solid #e5e7eb', borderRadius: 8, overflow: 'hidden' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 10px', background: '#f9fafb', border: 'none', cursor: 'pointer', fontSize: 12, color: '#6b7280' }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <FileText size={11} />
          {total} source{total !== 1 ? 's' : ''}
        </span>
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
      </button>
      {open && (
        <div>
          {filtered?.map(c => (
            <div key={c.ref} style={{ display: 'flex', gap: 8, padding: '6px 10px', borderTop: '0.5px solid #f3f4f6' }}>
              <span style={{ fontSize: 11, fontFamily: 'monospace', color: '#3b82f6', width: 22, flexShrink: 0 }}>[{c.ref}]</span>
              <div>
                <p style={{ fontSize: 12, fontWeight: 500, color: '#374151', margin: 0 }}>{c.filename}</p>
                <p style={{ fontSize: 11, color: '#9ca3af', margin: 0 }}>
                  Page {c.page_start ?? '?'}{c.section_title ? ` · ${c.section_title}` : ''}
                </p>
              </div>
            </div>
          ))}
          {webSources?.map((s: any) => (
            <div key={s.ref} style={{ display: 'flex', gap: 8, padding: '6px 10px', borderTop: '0.5px solid #f3f4f6' }}>
              <span style={{ fontSize: 11, fontFamily: 'monospace', color: '#059669', width: 22, flexShrink: 0 }}>[W{s.ref}]</span>
              <p style={{ fontSize: 12, color: '#374151', margin: 0 }}>{s.title}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Message({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user';
  return (
    <div style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start', marginBottom: 12 }}>
      {!isUser && (
        <div style={{ width: 28, height: 28, borderRadius: '50%', background: '#185FA5', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0, marginRight: 8, marginTop: 2 }}>F</div>
      )}
      <div style={{ maxWidth: '75%' }}>
        {!isUser && msg.intent && (
          <p style={{ fontSize: 11, color: '#9ca3af', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
            {msg.web_search_used && <Globe size={10} />}
            {msg.intent}
          </p>
        )}
        <div style={{
          padding: '10px 14px', borderRadius: 12,
          background: isUser ? '#185FA5' : '#f3f4f6',
          color: isUser ? 'white' : '#111',
          fontSize: 13, lineHeight: 1.6,
          borderBottomRightRadius: isUser ? 4 : 12,
          borderBottomLeftRadius: isUser ? 12 : 4,
        }}>
          {isUser ? msg.content : (
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
              table: ({ children }) => <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12, marginTop: 8 }}>{children}</table>,
              th: ({ children }) => <th style={{ background: '#e5e7eb', padding: '5px 8px', textAlign: 'left', fontWeight: 500, border: '0.5px solid #d1d5db' }}>{children}</th>,
              td: ({ children }) => <td style={{ padding: '5px 8px', border: '0.5px solid #e5e7eb' }}>{children}</td>,
            }}>
              {msg.streaming ? msg.content + '▋' : msg.content}
            </ReactMarkdown>
          )}
        </div>
        {!isUser && <CitationPanel citations={msg.citations} webSources={msg.web_sources} />}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const {
    messages, sessions, isStreaming, status, sessionId, quickQuestions,
    sendMessage, stop, newSession, loadSessions, loadSession, loadQuickQuestions, deleteSession,
  } = useChat();

  const [input, setInput] = useState('');
  const [webSearch, setWebSearch] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => { loadSessions(); loadQuickQuestions(); }, []);
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const handleSend = () => {
    if (!input.trim() || isStreaming) return;
    sendMessage(input, { enableWebSearch: webSearch });
    setInput('');
  };

  return (
    <div style={{ display: 'flex', height: '100vh', fontFamily: 'system-ui, sans-serif', fontSize: 14 }}>
      {/* Sidebar */}
      <div style={{ width: 220, background: '#f9fafb', borderRight: '0.5px solid #e5e7eb', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
        <div style={{ padding: '12px 10px', borderBottom: '0.5px solid #e5e7eb' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 22, height: 22, background: '#185FA5', borderRadius: 5, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontSize: 11, fontWeight: 700 }}>F</div>
              <span style={{ fontSize: 13, fontWeight: 600 }}>FinRAG Chat</span>
            </div>
          </div>
          <button onClick={newSession} style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 6, padding: '6px 8px', background: '#185FA5', color: 'white', border: 'none', borderRadius: 6, fontSize: 12, fontWeight: 500, cursor: 'pointer' }}>
            <Plus size={13} /> New chat
          </button>
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: '8px 6px' }}>
          <p style={{ fontSize: 10, color: '#9ca3af', padding: '0 4px', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>History</p>
          {sessions.map(s => (
            <div
              key={s.id}
              onClick={() => loadSession(s.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 4, padding: '6px 8px',
                borderRadius: 6, cursor: 'pointer', marginBottom: 1,
                background: sessionId === s.id ? '#EBF4FF' : 'transparent',
                color: sessionId === s.id ? '#185FA5' : '#374151',
              }}
            >
              <span style={{ flex: 1, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {s.title || 'Untitled'}
              </span>
              <button
                onClick={e => { e.stopPropagation(); deleteSession(s.id); }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af', padding: 2, opacity: 0, transition: 'opacity 0.1s' }}
                onMouseEnter={e => (e.currentTarget.style.opacity = '1')}
                onMouseLeave={e => (e.currentTarget.style.opacity = '0')}
              >
                <Trash2 size={11} />
              </button>
            </div>
          ))}
          {sessions.length === 0 && (
            <p style={{ fontSize: 11, color: '#9ca3af', padding: '8px 4px' }}>No previous chats</p>
          )}
        </div>

        <div style={{ padding: '8px 10px', borderTop: '0.5px solid #e5e7eb', fontSize: 11, color: '#9ca3af' }}>
          Grounded in indexed documents
        </div>
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Messages */}
        <div style={{ flex: 1, overflow: 'auto', padding: '1.5rem' }}>
          {messages.length === 0 && (
            <div style={{ textAlign: 'center', paddingTop: '3rem' }}>
              <div style={{ width: 44, height: 44, background: '#185FA5', borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 12px', color: 'white', fontSize: 20, fontWeight: 700 }}>F</div>
              <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>FinRAG</h2>
              <p style={{ fontSize: 13, color: '#6b7280', marginBottom: '2rem' }}>Ask anything about your indexed financial documents</p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center', maxWidth: 600, margin: '0 auto' }}>
                {quickQuestions.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => { sendMessage(q, { enableWebSearch: webSearch }); }}
                    style={{
                      padding: '8px 14px', border: '0.5px solid #e5e7eb', borderRadius: 20,
                      background: 'white', fontSize: 12, cursor: 'pointer', color: '#374151',
                    }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map(msg => <Message key={msg.id} msg={msg} />)}
          {status && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#9ca3af', fontSize: 12, padding: '4px 36px' }}>
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#185FA5', animation: 'pulse 1s infinite' }} />
              {status}
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div style={{ padding: '12px 1.5rem', borderTop: '0.5px solid #e5e7eb' }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <div style={{ flex: 1, border: '0.5px solid #d1d5db', borderRadius: 10, padding: '8px 12px', background: 'white' }}>
              <textarea
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }}}
                placeholder="Ask about performance, positions, fees..."
                rows={1}
                style={{ width: '100%', border: 'none', outline: 'none', resize: 'none', fontSize: 13, fontFamily: 'inherit', background: 'transparent' }}
              />
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
                <button
                  onClick={() => setWebSearch(w => !w)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, padding: '3px 8px',
                    border: '0.5px solid', borderColor: webSearch ? '#059669' : '#d1d5db',
                    borderRadius: 12, background: webSearch ? '#f0fdf4' : 'transparent',
                    color: webSearch ? '#059669' : '#9ca3af', cursor: 'pointer',
                  }}
                >
                  <Globe size={10} /> Web search {webSearch ? 'on' : 'off'}
                </button>
              </div>
            </div>
            <button
              onClick={isStreaming ? stop : handleSend}
              disabled={!isStreaming && !input.trim()}
              style={{
                width: 38, height: 38, borderRadius: 8, border: 'none', cursor: 'pointer',
                background: isStreaming ? '#ef4444' : '#185FA5',
                color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center',
                opacity: !isStreaming && !input.trim() ? 0.4 : 1,
              }}
            >
              {isStreaming ? <Square size={14} /> : <Send size={14} />}
            </button>
          </div>
        </div>
      </div>

      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}`}</style>
    </div>
  );
}
