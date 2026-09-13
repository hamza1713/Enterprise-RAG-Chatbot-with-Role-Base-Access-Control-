import {
  useState,
  useEffect,
  useRef,
  useCallback,
  type KeyboardEvent,
} from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useAuthStore } from '../store/authStore';
import { streamChat } from '../api/chat';
import type { ChatChunk } from '../api/chat';
import client from '../api/client';
import { openPdfPreview } from '../api/documents';
import {
  Send,
  Trash2,
  Database,
  FileText,
  CornerDownRight,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Copy,
  Check,
  StopCircle,
  Bot,
  User as UserIcon,
  Zap,
  Sparkles,
  BarChart2,
} from 'lucide-react';

/* ─── Types ─────────────────────────────────────────────────────────────────── */

interface LocalMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  mode?: string;
  sql?: string | null;
  sources?: string[];
  fallback?: boolean;
  isStreaming?: boolean;
  timestamp: Date;
}

interface DocInfo {
  filename: string;
  filepath: string;
}

/* ─── Streaming cursor component ─────────────────────────────────────────────── */

function StreamingCursor() {
  return (
    <span
      style={{
        display: 'inline-block',
        width: '2px',
        height: '1.1em',
        background: 'var(--primary-hover)',
        borderRadius: '1px',
        marginLeft: '2px',
        verticalAlign: 'text-bottom',
        animation: 'cursor-blink 0.7s ease-in-out infinite',
      }}
    />
  );
}

/* ─── Thinking indicator ─────────────────────────────────────────────────────── */

function ThinkingIndicator() {
  return (
    <div className="thinking-indicator">
      <div className="thinking-dots">
        <span className="thinking-dot" />
        <span className="thinking-dot" />
        <span className="thinking-dot" />
      </div>
      <span className="thinking-label">FinSight is thinking…</span>
    </div>
  );
}

/* ─── Copy button ─────────────────────────────────────────────────────────────── */

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };
  return (
    <button
      onClick={handleCopy}
      className="msg-action-btn"
      title={copied ? 'Copied!' : 'Copy message'}
    >
      {copied ? <Check size={13} color="#34D399" /> : <Copy size={13} />}
    </button>
  );
}

/* ─── Main ChatPage component ────────────────────────────────────────────────── */

export default function ChatPage() {
  const { token, username, role } = useAuthStore();

  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [accessibleDocs, setAccessibleDocs] = useState<DocInfo[]>([]);
  const [openSources, setOpenSources] = useState<Record<string, boolean>>({});
  const [openSql, setOpenSql] = useState<Record<string, boolean>>({});
  const [fileContentCache, setFileContentCache] = useState<Record<string, any>>({});
  const [loadingFile, setLoadingFile] = useState<Record<string, boolean>>({});
  const [tokenCount, setTokenCount] = useState(0);
  const [previewError, setPreviewError] = useState('');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<boolean>(false);
  const controllerRef = useRef<AbortController | null>(null);
  useEffect(() => () => controllerRef.current?.abort(), []);
  const lastStreamIdRef = useRef<string>('');

  /* ─── Fetch document list ─────────────────────────────────────────── */

  useEffect(() => {
    const fetchDocs = async () => {
      try {
        const res = await client.get('/documents');
        setAccessibleDocs(res.data);
      } catch {}
    };
    fetchDocs();
  }, []);

  /* ─── Auto scroll to bottom ──────────────────────────────────────── */

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  /* ─── Auto-resize textarea ────────────────────────────────────────── */

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px';
  }, [inputValue]);

  /* ─── Generate unique id ──────────────────────────────────────────── */

  const genId = () =>
    `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  /* ─── Send message ────────────────────────────────────────────────── */

  const handleSend = useCallback(
    async (questionText: string) => {
      const q = questionText.trim();
      if (!q || isSending || !token) return;

      abortRef.current = false;
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setIsSending(true);
      setInputValue('');
      setTokenCount(0);

      const userId = genId();
      const assistantId = genId();
      lastStreamIdRef.current = assistantId;

      const userMsg: LocalMessage = {
        id: userId,
        role: 'user',
        content: q,
        timestamp: new Date(),
      };

      const assistantPlaceholder: LocalMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        isStreaming: true,
        mode: 'RAG',
        sources: [],
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, userMsg, assistantPlaceholder]);

      let accumulated = '';
      let resolvedMode = 'RAG';
      let resolvedSql: string | null = null;
      let resolvedSources: string[] = [];
      let resolvedFallback = false;
      let localTokenCount = 0;

      await streamChat(
        q,
        token,
        (chunk: ChatChunk) => {
          if (controller.signal.aborted || abortRef.current) return;

          if (chunk.type === 'init') {
            if (chunk.mode) resolvedMode = chunk.mode;
          } else if (chunk.type === 'fallback') {
            resolvedFallback = true;
            if (chunk.mode) resolvedMode = chunk.mode;
          } else if (chunk.type === 'token') {
            accumulated += chunk.content || '';
            localTokenCount++;
            setTokenCount(localTokenCount);
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, content: accumulated }
                  : m
              )
            );
          } else if (chunk.type === 'metadata') {
            if (chunk.sql) resolvedSql = chunk.sql;
            if (chunk.sources) resolvedSources = chunk.sources;
            if (chunk.fallback !== undefined) resolvedFallback = chunk.fallback;
          } else if (chunk.type === 'error') {
            accumulated = chunk.answer || '⚠️ Something went wrong.';
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, content: accumulated } : m
              )
            );
          }
        },
        () => {
          if (controller.signal.aborted) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    isStreaming: false,
                    mode: resolvedMode,
                    sql: resolvedSql,
                    sources: resolvedSources,
                    fallback: resolvedFallback,
                    timestamp: new Date(),
                  }
                : m
            )
          );
          setIsSending(false);
        },
        (err) => {
          if (controller.signal.aborted) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    isStreaming: false,
                    content: `**⚠️ Connection error:** ${err.message || 'Unable to reach the AI service. Check that the backend is running.'}`,
                  }
                : m
            )
          );
          setIsSending(false);
        },
        controller.signal
      );
    },
    [isSending, token]
  );

  /* ─── Stop streaming ──────────────────────────────────────────────── */

  const handleStop = () => {
    abortRef.current = true;
    controllerRef.current?.abort();
    // Mark the streaming message as done
    setMessages((prev) =>
      prev.map((m) =>
        m.id === lastStreamIdRef.current
          ? { ...m, isStreaming: false }
          : m
      )
    );
    setIsSending(false);
  };

  /* ─── Clear chat ──────────────────────────────────────────────────── */

  const handleClear = () => {
    handleStop();
    setMessages([]);
    setOpenSources({});
    setOpenSql({});
    setTokenCount(0);
    textareaRef.current?.focus();
  };

  /* ─── Keyboard handler ────────────────────────────────────────────── */

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSend(inputValue);
    }
  };

  /* ─── Source toggle with lazy content load ────────────────────────── */

  const toggleSource = async (filename: string, filepath: string) => {
    const key = `${filename}-${filepath}`;
    const willOpen = !openSources[key];
    setOpenSources((prev) => ({ ...prev, [key]: willOpen }));

    if (willOpen && !fileContentCache[filepath]) {
      const ext = filename.split('.').pop()?.toLowerCase();
      if (ext === 'pdf') return;

      setLoadingFile((prev) => ({ ...prev, [filepath]: true }));
      try {
        const res = await client.get('/documents/content', {
          params: { filepath },
        });
        setFileContentCache((prev) => ({ ...prev, [filepath]: res.data }));
      } catch {} finally {
        setLoadingFile((prev) => ({ ...prev, [filepath]: false }));
      }
    }
  };

  const openPdfTab = async (filepath: string) => {
    setPreviewError('');
    try { await openPdfPreview(filepath); }
    catch (error) { setPreviewError(error instanceof Error ? error.message : 'Preview unavailable.'); }
  };

  /* ─── Source file content renderer ───────────────────────────────── */

  const renderSourceContent = (_filename: string, filepath: string) => {
    const cache = fileContentCache[filepath];
    if (loadingFile[filepath]) {
      return (
        <div className="source-loading">
          <div className="source-loading-spinner" />
          Loading file content…
        </div>
      );
    }
    if (!cache) {
      return (
        <div className="source-error">⚠️ Content unavailable or access restricted.</div>
      );
    }
    if (cache.type === 'csv') {
      return (
        <div className="fs-table-wrap" style={{ maxHeight: '260px', marginTop: '8px' }}>
          <table className="fs-table">
            <thead>
              <tr>
                <th style={{ width: '50px', minWidth: '50px', textAlign: 'center', background: '#233331', color: 'var(--primary-hover)', fontWeight: 'bold', position: 'sticky', left: 0, zIndex: 12 }}>#</th>
                {cache.columns?.map((col: string, i: number) => (
                  <th key={i}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cache.data?.slice(0, 30).map((row: any, rIdx: number) => (
                <tr key={rIdx}>
                  <td style={{ textAlign: 'center', background: 'rgba(94,157,128, 0.05)', fontWeight: 'bold', color: 'var(--text-muted)', position: 'sticky', left: 0, zIndex: 5, borderRight: '1px solid rgba(94,157,128, 0.15)' }}>
                    {rIdx + 1}
                  </td>
                  {cache.columns?.map((col: string, cIdx: number) => (
                    <td key={cIdx}>
                      {row[col] === null ? (
                        <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>null</span>
                      ) : String(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {cache.data?.length > 30 && (
            <div className="source-table-footer">
              Showing 30 of {cache.data.length} rows — open in Explorer for full view.
            </div>
          )}
        </div>
      );
    }
    if (cache.type === 'markdown') {
      return (
        <div
          className="chat-message-content"
          style={{
            marginTop: '8px',
            padding: '14px',
            background: 'rgba(13,23,25,0.6)',
            borderRadius: '8px',
            border: '1px solid var(--border)',
          }}
        >
          <ReactMarkdown 
            remarkPlugins={[remarkGfm]}
            components={{
              table: ({ node: _node, ...props }) => (
                <div className="fs-table-wrap">
                  <table className="fs-table" {...props} />
                </div>
              )
            }}
          >
            {cache.content}
          </ReactMarkdown>
        </div>
      );
    }
    return null;
  };

  /* ─── Time formatter ──────────────────────────────────────────────── */

  const formatTime = (d: Date) =>
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  /* ─── Suggestion pills ────────────────────────────────────────────── */

  const suggestions = [
    { icon: <FileText size={18} />, text: 'Summarize our employee handbook' },
    { icon: <BarChart2 size={18} />, text: `Summarize the key findings in ${role?.toLowerCase() === 'c-level' ? 'our department' : `our ${role || 'department'}`} reports` },
    { icon: <Database size={18} />, text: 'What datasets are available to my role?' },
    { icon: <Sparkles size={18} />, text: 'What are our company leave policies?' },
  ];

  /* ─── Render ──────────────────────────────────────────────────────── */

  return (
    <div className="chat-page-root">
      {previewError && <div className="form-error" role="alert">{previewError}</div>}
      {/* ── Header ── */}
      <div className="chat-page-header">
        <div>
          <h1 className="fs-title" style={{ fontSize: '20px', marginBottom: '2px' }}>
            <Bot size={20} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '8px' }} />
            Your AI assistant
          </h1>
          <p className="fs-subtitle">
            Ask questions across your documents, tables, and reports.{' '}
            <kbd className="kbd">Enter</kbd> to send · <kbd className="kbd">Shift+Enter</kbd> for newline
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {messages.length > 0 && (
            <span className="chat-msg-count">{messages.length} messages</span>
          )}
          {messages.length > 0 && (
            <button
              className="fs-btn fs-btn-danger"
              onClick={handleClear}
              style={{ padding: '7px 14px', fontSize: '13px' }}
            >
              <Trash2 size={14} />
              <span>Clear</span>
            </button>
          )}
        </div>
      </div>

      {/* ── Messages window ── */}
      <div className="chat-window">
        {messages.length === 0 ? (
          /* ── Empty / welcome state ── */
          <div className="chat-welcome">
            <div className="chat-welcome-icon">
              <Zap size={32} color="var(--primary-hover)" />
            </div>
            <span className="eyebrow" style={{ marginBottom: 14 }}>A LITTLE CURIOSITY. A CLEARER PICTURE.</span>
            <h2 className="chat-welcome-title">What would you like to discover?</h2>
            <p className="chat-welcome-sub">
              Welcome, {username || 'there'}. Explore your team's knowledge,
              make sense of your data, and find answers with sources.
            </p>
            <div className="chat-suggestions-grid">
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  className="chat-suggestion-card"
                  onClick={() => handleSend(s.text)}
                >
                  <span className="chat-suggestion-icon">{s.icon}</span>
                  <span>{s.text}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* ── Message list ── */
          <div className="chat-messages-list">
            {messages.map((msg) => {
              const isAssistant = msg.role === 'assistant';
              const isStreaming = msg.isStreaming === true;
              const showSqlKey = msg.id + '-sql';
              const showSql = openSql[showSqlKey] || false;
              const isGreeting = msg.mode === 'GREETING';
              const isDenied = msg.mode === 'DENIED';

              return (
                <div
                  key={msg.id}
                  className={`chat-msg-row ${isAssistant ? 'chat-msg-row--assistant' : 'chat-msg-row--user'}`}
                >
                  {/* Avatar */}
                  <div className={`chat-msg-avatar ${isAssistant ? 'chat-msg-avatar--ai' : 'chat-msg-avatar--user'}`}>
                    {isAssistant ? <Bot size={16} /> : <UserIcon size={15} />}
                  </div>

                  {/* Bubble */}
                  <div className={`chat-msg-bubble ${isAssistant ? 'chat-msg-bubble--ai' : 'chat-msg-bubble--user'}`}>
                    {/* Sender label + timestamp */}
                    <div className="chat-msg-meta">
                      <span className="chat-msg-sender">
                        {isAssistant ? 'FinSight AI' : (username || 'You')}
                      </span>
                      <span className="chat-msg-time">{formatTime(msg.timestamp)}</span>
                    </div>

                    {/* Content area */}
                    {isStreaming && !msg.content ? (
                      <ThinkingIndicator />
                    ) : (
                      <div className="chat-message-content">
                        <ReactMarkdown 
                          remarkPlugins={[remarkGfm]}
                          components={{
                            table: ({ node: _node, ...props }) => (
                              <div className="fs-table-wrap" style={{ margin: '12px 0' }}>
                                <table className="fs-table" {...props} />
                              </div>
                            )
                          }}
                        >
                          {msg.content}
                        </ReactMarkdown>
                        {isStreaming && msg.content && <StreamingCursor />}
                      </div>
                    )}

                    {/* Streaming token counter */}
                    {isStreaming && tokenCount > 0 && (
                      <div className="chat-token-counter">{tokenCount} tokens</div>
                    )}

                    {/* Actions (copy, etc.) — shown when not streaming */}
                    {isAssistant && !isStreaming && msg.content && (
                      <div className="chat-msg-actions">
                        <CopyButton text={msg.content} />
                      </div>
                    )}

                    {/* Mode badges */}
                    {isAssistant && !isStreaming && !isGreeting && !isDenied && (
                      <div className="chat-msg-badges">
                        {msg.sql ? (
                          <span className="chat-badge chat-badge--sql">
                            <Database size={10} /> SQL query
                          </span>
                        ) : (
                          <span className="chat-badge chat-badge--rag">
                            <FileText size={10} /> RAG document
                          </span>
                        )}
                        {msg.fallback && (
                          <span className="chat-badge chat-badge--fallback">↩ Fallback</span>
                        )}
                      </div>
                    )}

                    {/* SQL viewer */}
                    {isAssistant && msg.sql && !isStreaming && (
                      <div className="chat-sql-section">
                        <button
                          className="chat-sql-toggle"
                          onClick={() =>
                            setOpenSql((prev) => ({
                              ...prev,
                              [showSqlKey]: !showSql,
                            }))
                          }
                        >
                          <Database size={12} />
                          <span>{showSql ? 'Hide SQL' : 'View Generated SQL'}</span>
                          {showSql ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                        </button>
                        {showSql && (
                          <pre className="chat-sql-pre">
                            <code>{msg.sql}</code>
                          </pre>
                        )}
                      </div>
                    )}

                    {/* Sources */}
                    {isAssistant && !isStreaming && msg.sources && msg.sources.length > 0 && (
                      <div className="chat-sources-section">
                        <div className="chat-sources-title">
                          <CornerDownRight size={12} /> Referenced Sources
                        </div>
                        {msg.sources.map((src, sIdx) => {
                          const docMatch = accessibleDocs.find((d) => d.filename === src);
                          const filepath = docMatch?.filepath || '';
                          const isPdf = src.toLowerCase().endsWith('.pdf');
                          const key = `${src}-${filepath}`;
                          const isExpanded = openSources[key] || false;
                          const ext = src.split('.').pop()?.toLowerCase();
                          const icon = ext === 'pdf' ? '📑' : ext === 'csv' ? '📊' : '📄';

                          return (
                            <div key={sIdx} className="chat-source-item">
                              <div
                                className="chat-source-header"
                                onClick={() =>
                                  isPdf ? openPdfTab(filepath) : toggleSource(src, filepath)
                                }
                              >
                                <span className="chat-source-name">
                                  {icon} {src}
                                </span>
                                {isPdf ? (
                                  <span className="chat-source-pdf-link">
                                    <ExternalLink size={11} /> Open
                                  </span>
                                ) : (
                                  <span className="chat-source-chevron">
                                    {isExpanded ? (
                                      <ChevronUp size={13} />
                                    ) : (
                                      <ChevronDown size={13} />
                                    )}
                                  </span>
                                )}
                              </div>
                              {isExpanded && !isPdf && (
                                <div className="chat-source-body">
                                  {renderSourceContent(src, filepath)}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* ── Input area ── */}
      <div className="chat-input-area">
        {/* Status row */}
        {isSending && (
          <div className="chat-status-row">
            <div className="chat-status-dot" />
            <span>Generating response…</span>
            <button className="chat-stop-btn" onClick={handleStop}>
              <StopCircle size={13} /> Stop
            </button>
          </div>
        )}

        <div className="chat-input-container">
          <textarea
            aria-label="Ask your AI assistant"
            maxLength={8000}
            ref={textareaRef}
            className="chat-textarea"
            placeholder="Ask a question about your workspace data… (Enter to send)"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isSending}
            rows={1}
          />

          <button
            className={`chat-send-btn ${isSending ? 'chat-send-btn--sending' : ''}`}
            onClick={() => handleSend(inputValue)}
            disabled={isSending || !inputValue.trim()}
            title="Send (Enter)"
          >
            <Send size={17} />
          </button>
        </div>

        <div className="chat-input-footer">
          <span>Answers from your workspace. Review sources before making decisions.</span>
          {inputValue.length > 0 && (
            <span className="chat-char-count">{inputValue.length} chars</span>
          )}
        </div>
      </div>
    </div>
  );
}
