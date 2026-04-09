import React, { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useChat, ChatMessage, Citation } from '../hooks/useChat';
import {
  Send, Square, Globe, ChevronDown, ChevronRight,
  FileText, ExternalLink, Zap, BookOpen, BarChart2, User,
  Trash2, Plus,
} from 'lucide-react';
import clsx from 'clsx';

const INTENT_ICONS: Record<string, any> = {
  summary: BookOpen,
  comparison: BarChart2,
  personnel: User,
  temporal: Zap,
  metric: BarChart2,
  general: FileText,
};

const SUGGESTED = [
  'Show me an investment summary for the latest quarter',
  'Compare the top 2 funds by expense ratio',
  'Any personnel changes in the past 6 months?',
  'What is the current AUM across all funds?',
];

function CitationPanel({ citations, webSources }: { citations?: Citation[]; webSources?: any[] }) {
  const [open, setOpen] = useState(false);
  // Filter to only high-relevance citations if relevance scores are present
  const filteredCitations = citations?.filter(c => {
    const score = (c as any).relevance_score;
    return score === undefined || score === null || score > 0;
  });
  const total = (filteredCitations?.length ?? 0) + (webSources?.length ?? 0);
  if (!total) return null;

  return (
    <div className="mt-3 border border-gray-100 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 transition text-xs text-gray-500"
      >
        <span className="flex items-center gap-1.5">
          <FileText size={12} />
          {total} source{total !== 1 ? 's' : ''}
        </span>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {open && (
        <div className="divide-y divide-gray-50">
          {filteredCitations?.map(c => (
            <div key={c.ref} className="flex items-start gap-2 px-3 py-2">
              <span className="text-xs font-mono text-blue-500 w-6 shrink-0">[{c.ref}]</span>
              <div className="min-w-0">
                <p className="text-xs font-medium text-gray-700 truncate">{c.filename}</p>
                <p className="text-xs text-gray-400">
                  Page {c.page_start ?? '?'}
                  {c.section_title ? ` · ${c.section_title}` : ''}
                </p>
              </div>
            </div>
          ))}
          {webSources?.map((s: any) => (
            <div key={s.ref} className="flex items-start gap-2 px-3 py-2">
              <span className="text-xs font-mono text-green-500 w-6 shrink-0">[W{s.ref}]</span>
              <div className="min-w-0 flex items-center gap-1">
                <p className="text-xs text-gray-700 truncate">{s.title}</p>
                <a href={s.url} target="_blank" rel="noreferrer" className="shrink-0">
                  <ExternalLink size={10} className="text-gray-400 hover:text-blue-500" />
                </a>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const IntentIcon = msg.intent ? (INTENT_ICONS[msg.intent] ?? FileText) : null;

  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] bg-blue-600 text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed">
          {msg.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 max-w-[85%]">
      <div className="w-7 h-7 rounded-full bg-slate-800 flex items-center justify-center shrink-0 mt-0.5">
        <span className="text-white text-xs font-bold">F</span>
      </div>
      <div className="flex-1 min-w-0">
        {/* Intent badge */}
        {msg.intent && IntentIcon && (
          <div className="flex items-center gap-1.5 mb-2">
            <IntentIcon size={11} className="text-gray-400" />
            <span className="text-xs text-gray-400 capitalize">{msg.intent}</span>
          </div>
        )}

        {/* Content */}
        <div className={clsx(
          'bg-white border border-gray-100 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-gray-800 leading-relaxed shadow-sm',
          msg.streaming && 'border-blue-100'
        )}>
          {msg.content ? (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                table: ({ children }) => (
                  <div className="overflow-x-auto my-2">
                    <table className="text-xs border-collapse w-full">{children}</table>
                  </div>
                ),
                th: ({ children }) => (
                  <th className="bg-gray-50 border border-gray-200 px-3 py-1.5 text-left font-medium text-gray-700">{children}</th>
                ),
                td: ({ children }) => (
                  <td className="border border-gray-200 px-3 py-1.5 text-gray-600">{children}</td>
                ),
                code: ({ children }) => (
                  <code className="bg-gray-100 px-1 py-0.5 rounded text-xs font-mono">{children}</code>
                ),
              }}
            >
              {msg.content}
            </ReactMarkdown>
          ) : (
            <div className="flex items-center gap-2 text-gray-400">
              <span className="inline-block w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="inline-block w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="inline-block w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
          )}
        </div>

        {/* Citations + meta */}
        {!msg.streaming && (
          <>
            <CitationPanel citations={msg.citations} webSources={msg.web_sources} />
            {msg.latency_ms && (
              <p className="text-xs text-gray-300 mt-1 ml-1">
                {(msg.latency_ms / 1000).toFixed(1)}s
                {msg.web_search_used && ' · web search used'}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const [query, setQuery] = useState('');
  const [webSearch, setWebSearch] = useState(false);
  const [outputFormat, setOutputFormat] = useState<'paragraph' | 'bullets' | 'table'>('paragraph');
  const bottomRef = useRef<HTMLDivElement>(null);

  const { messages, isStreaming, status, sendMessage, stop, clearMessages } = useChat({
    enableWebSearch: webSearch,
    outputFormat,
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, status]);

  const handleSend = () => {
    const q = query.trim();
    if (!q || isStreaming) return;
    setQuery('');
    sendMessage(q);
  };

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50 font-sans">
      {/* Header */}
      <header className="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-5 shadow-sm shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-slate-800 flex items-center justify-center text-white text-xs font-bold">F</div>
          <span className="font-semibold text-sm text-gray-800">FinRAG</span>
          <span className="text-gray-300 text-xs">· Financial Document Intelligence</span>
        </div>
        <div className="flex items-center gap-3">
          {/* Format selector */}
          <select
            value={outputFormat}
            onChange={e => setOutputFormat(e.target.value as any)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 text-gray-600 focus:outline-none"
          >
            <option value="paragraph">Paragraph</option>
            <option value="bullets">Bullet Points</option>
            <option value="table">Table</option>
          </select>

          {/* Web search toggle */}
          <button
            onClick={() => setWebSearch(w => !w)}
            className={clsx(
              'flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition',
              webSearch
                ? 'bg-green-50 border-green-200 text-green-700'
                : 'border-gray-200 text-gray-500 hover:bg-gray-50'
            )}
          >
            <Globe size={13} />
            Web Search {webSearch ? 'ON' : 'OFF'}
          </button>

          {/* New chat */}
          <button
            onClick={clearMessages}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 transition"
          >
            <Plus size={13} />
            New Chat
          </button>
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-5">
        {messages.length === 0 && (
          <div className="max-w-2xl mx-auto text-center space-y-6 pt-12">
            <div className="w-14 h-14 rounded-2xl bg-slate-800 flex items-center justify-center mx-auto">
              <span className="text-white text-2xl font-bold">F</span>
            </div>
            <div>
              <h1 className="text-2xl font-semibold text-gray-900">FinRAG Enterprise</h1>
              <p className="text-gray-500 text-sm mt-2">
                Ask questions about your financial documents. All answers are grounded in source documents.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-left">
              {SUGGESTED.map(s => (
                <button
                  key={s}
                  onClick={() => sendMessage(s)}
                  className="text-sm text-gray-700 bg-white border border-gray-200 rounded-xl px-4 py-3 hover:border-blue-300 hover:bg-blue-50 transition text-left shadow-sm"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map(msg => (
          <div key={msg.id} className="max-w-3xl mx-auto">
            <MessageBubble msg={msg} />
          </div>
        ))}

        {/* Status indicator */}
        {isStreaming && status && (
          <div className="max-w-3xl mx-auto flex items-center gap-2 text-xs text-gray-400 pl-10">
            <span className="inline-block w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse" />
            {status}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="bg-white border-t border-gray-200 px-4 py-4 shrink-0">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-end gap-3 bg-white border border-gray-200 rounded-2xl px-4 py-3 shadow-sm focus-within:border-blue-400 focus-within:ring-1 focus-within:ring-blue-100 transition">
            <textarea
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Ask about your financial documents…"
              rows={1}
              disabled={isStreaming}
              className="flex-1 resize-none text-sm text-gray-800 placeholder-gray-400 focus:outline-none leading-relaxed"
              style={{ maxHeight: '120px', overflowY: 'auto' }}
            />
            {isStreaming ? (
              <button
                onClick={stop}
                className="w-8 h-8 rounded-lg bg-red-500 hover:bg-red-600 flex items-center justify-center transition shrink-0"
              >
                <Square size={14} className="text-white" />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!query.trim()}
                className="w-8 h-8 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-40 flex items-center justify-center transition shrink-0"
              >
                <Send size={14} className="text-white" />
              </button>
            )}
          </div>
          <p className="text-xs text-gray-400 text-center mt-2">
            Responses are grounded in indexed documents only · Citations shown for every claim
          </p>
        </div>
      </div>
    </div>
  );
}
