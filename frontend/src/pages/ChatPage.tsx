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
import { streamChat, type ChatChunk } from '../api/chat';
import client from '../api/client';
import { openPdfPreview } from '../api/documents';
import {
  createThread,
  deleteThread,
  fetchThreadMessages,
  fetchThreads,
  renameThread,
} from '../api/threads';
import type { AgentStep, ChartSpec, ChatThread, CitationItem } from '../types';
import ThreadSidebar from '../components/chat/ThreadSidebar';
import AgentStepsBar from '../components/chat/AgentStepsBar';
import ChartRenderer from '../components/chat/ChartRenderer';
import CitationDrawer from '../components/chat/CitationDrawer';
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
  ShieldCheck,
} from 'lucide-react';

interface LocalMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  mode?: string;
  sql?: string | null;
  sources?: string[];
  citations?: CitationItem[];
  chart_spec?: ChartSpec | null;
  agent_steps?: AgentStep[];
  fallback?: boolean;
  isStreaming?: boolean;
  timestamp: Date;
}

interface DocInfo {
  id?: number;
  filename: string;
  filepath: string;
}

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

function ThinkingIndicator() {
  return (
    <div className="thinking-indicator">
      <div className="thinking-dots">
        <span className="thinking-dot" />
        <span className="thinking-dot" />
        <span className="thinking-dot" />
      </div>
      <span className="thinking-label">FinSight agent is working…</span>
    </div>
  );
}

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
      type="button"
      onClick={handleCopy}
      className="msg-action-btn"
      title={copied ? 'Copied!' : 'Copy message'}
    >
      {copied ? <Check size={13} color="#34D399" /> : <Copy size={13} />}
    </button>
  );
}

function upsertStep(steps: AgentStep[], incoming: AgentStep): AgentStep[] {
  const idx = steps.findIndex((s) => s.node === incoming.node && s.status === 'running');
  if (idx >= 0) {
    const next = [...steps];
    next[idx] = incoming;
    return next;
  }
  const sameIdx = steps.findIndex((s) => s.node === incoming.node && s.label === incoming.label);
  if (sameIdx >= 0) {
    const next = [...steps];
    next[sameIdx] = incoming;
    return next;
  }
  return [...steps, incoming];
}

export default function ChatPage() {
  const { username, role, isAuthenticated } = useAuthStore();

  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [accessibleDocs, setAccessibleDocs] = useState<DocInfo[]>([]);
  const [openSources, setOpenSources] = useState<Record<string, boolean>>({});
  const [fileContentCache, setFileContentCache] = useState<Record<string, any>>({});
  const [loadingFile, setLoadingFile] = useState<Record<string, boolean>>({});
  const [tokenCount, setTokenCount] = useState(0);
  const [previewError, setPreviewError] = useState('');
  const [selectedCitation, setSelectedCitation] = useState<CitationItem | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<boolean>(false);
  const controllerRef = useRef<AbortController | null>(null);
  const lastStreamIdRef = useRef<string>('');

  useEffect(() => () => controllerRef.current?.abort(), []);

  const refreshThreads = useCallback(async () => {
    setThreadsLoading(true);
    try {
      const list = await fetchThreads();
      setThreads(list);
    } catch {
      // Offline / transient network errors stay silent cleanly
    } finally {
      setThreadsLoading(false);
    }
  }, []);

  useEffect(() => {
    const fetchDocs = async () => {
      try {
        const res = await client.get('/documents');
        setAccessibleDocs(res.data || []);
      } catch {}
    };
    void fetchDocs();
    void refreshThreads();
  }, [refreshThreads]);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px';
  }, [inputValue]);

  const genId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  const handleSelectThread = async (threadId: string) => {
    controllerRef.current?.abort();
    setIsSending(false);
    setSelectedCitation(null);
    setActiveThreadId(threadId);
    try {
      const data = await fetchThreadMessages(threadId);
      setMessages(
        (data.messages || []).map((m) => ({
          id: `db-${m.id}`,
          role: m.role,
          content: m.content,
          mode: m.mode || undefined,
          sql: m.sql,
          citations: m.citations || [],
          chart_spec: m.chart_spec || null,
          agent_steps: m.agent_steps || [],
          sources: Array.from(new Set((m.citations || []).map((c) => c.source))),
          timestamp: m.created_at ? new Date(m.created_at) : new Date(),
        }))
      );
    } catch {
      setPreviewError('Failed to load conversation history.');
    }
  };

  const handleNewThread = async () => {
    controllerRef.current?.abort();
    setIsSending(false);
    setSelectedCitation(null);
    setMessages([]);
    setOpenSources({});
    try {
      const created = await createThread('New Conversation');
      setActiveThreadId(created.id);
      setThreads((prev) => [created, ...prev]);
    } catch {
      setActiveThreadId(null);
    }
    textareaRef.current?.focus();
  };

  const handleRenameThread = async (threadId: string, title: string) => {
    const updated = await renameThread(threadId, title);
    setThreads((prev) => prev.map((t) => (t.id === threadId ? updated : t)));
  };

  const handleDeleteThread = async (threadId: string) => {
    await deleteThread(threadId);
    setThreads((prev) => prev.filter((t) => t.id !== threadId));
    if (activeThreadId === threadId) {
      setActiveThreadId(null);
      setMessages([]);
      setSelectedCitation(null);
    }
  };

  const handleSend = useCallback(
    async (questionText: string) => {
      const q = questionText.trim();
      if (!q || isSending || !isAuthenticated) return;

      abortRef.current = false;
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setIsSending(true);
      setInputValue('');
      setTokenCount(0);
      setSelectedCitation(null);

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
        citations: [],
        agent_steps: [],
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, userMsg, assistantPlaceholder]);

      let accumulated = '';
      let resolvedMode = 'RAG';
      let resolvedSql: string | null = null;
      let resolvedSources: string[] = [];
      let resolvedCitations: CitationItem[] = [];
      let resolvedChart: ChartSpec | null = null;
      let resolvedSteps: AgentStep[] = [];
      let resolvedFallback = false;
      let resolvedThreadId = activeThreadId;
      let localTokenCount = 0;

      const recentHistory = messages
        .filter((m) => m.content && !m.isStreaming)
        .slice(-6)
        .map((m) => ({ role: m.role, content: m.content }));

      await streamChat(
        q,
        (chunk: ChatChunk) => {
          if (controller.signal.aborted || abortRef.current) return;

          if (chunk.type === 'init') {
            if (chunk.mode) resolvedMode = chunk.mode;
            if (chunk.thread_id) {
              resolvedThreadId = chunk.thread_id;
              setActiveThreadId(chunk.thread_id);
            }
          } else if (chunk.type === 'step' && chunk.node && chunk.label) {
            const stepObj: AgentStep = {
              node: chunk.node,
              label: chunk.label,
              status: chunk.status || 'done',
              detail: chunk.detail,
            };
            resolvedSteps = upsertStep(resolvedSteps, stepObj);
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, agent_steps: resolvedSteps } : m))
            );
          } else if (chunk.type === 'fallback') {
            resolvedFallback = true;
            if (chunk.mode) resolvedMode = chunk.mode;
          } else if (chunk.type === 'chart' && chunk.chart_spec) {
            resolvedChart = chunk.chart_spec;
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, chart_spec: resolvedChart } : m))
            );
          } else if (chunk.type === 'citation' && chunk.citations) {
            resolvedCitations = chunk.citations;
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, citations: resolvedCitations } : m))
            );
          } else if (chunk.type === 'token') {
            accumulated += chunk.content || '';
            localTokenCount++;
            setTokenCount(localTokenCount);
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, content: accumulated } : m))
            );
          } else if (chunk.type === 'metadata') {
            if (chunk.thread_id) resolvedThreadId = chunk.thread_id;
            if (chunk.mode) resolvedMode = chunk.mode;
            if (chunk.sql !== undefined) resolvedSql = chunk.sql || null;
            if (chunk.sources) resolvedSources = chunk.sources;
            if (chunk.citations) resolvedCitations = chunk.citations;
            if (chunk.chart_spec !== undefined) resolvedChart = chunk.chart_spec || null;
            if (chunk.agent_steps) resolvedSteps = chunk.agent_steps;
            if (chunk.fallback !== undefined) resolvedFallback = chunk.fallback;
          } else if (chunk.type === 'error') {
            accumulated = chunk.content || chunk.answer || '⚠️ Something went wrong.';
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, content: accumulated } : m))
            );
          }
        },
        () => {
          if (controller.signal.aborted) return;
          if (resolvedThreadId) setActiveThreadId(resolvedThreadId);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    isStreaming: false,
                    mode: resolvedMode,
                    sql: resolvedSql,
                    sources: resolvedSources,
                    citations: resolvedCitations,
                    chart_spec: resolvedChart,
                    agent_steps: resolvedSteps,
                    fallback: resolvedFallback,
                    timestamp: new Date(),
                  }
                : m
            )
          );
          setIsSending(false);
          void refreshThreads();
        },
        (err) => {
          if (controller.signal.aborted) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    isStreaming: false,
                    content: `**⚠️ Connection error:** ${err.message || 'Unable to reach the AI service.'}`,
                  }
                : m
            )
          );
          setIsSending(false);
        },
        controller.signal,
        recentHistory,
        activeThreadId
      );
    },
    [isSending, isAuthenticated, messages, activeThreadId, refreshThreads]
  );

  const handleStop = () => {
    abortRef.current = true;
    controllerRef.current?.abort();
    setMessages((prev) =>
      prev.map((m) => (m.id === lastStreamIdRef.current ? { ...m, isStreaming: false } : m))
    );
    setIsSending(false);
  };

  const handleClear = () => {
    handleStop();
    setMessages([]);
    setOpenSources({});
    setTokenCount(0);
    setActiveThreadId(null);
    setSelectedCitation(null);
    textareaRef.current?.focus();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void handleSend(inputValue);
    }
  };

  const toggleSource = async (filename: string, filepath: string, docId?: number | null) => {
    const key = `${filename}-${filepath || docId || ''}`;
    const willOpen = !openSources[key];
    setOpenSources((prev) => ({ ...prev, [key]: willOpen }));

    const cacheKey = filepath || String(docId || filename);
    if (willOpen && !fileContentCache[cacheKey]) {
      const ext = filename.split('.').pop()?.toLowerCase();
      if (ext === 'pdf') return;

      setLoadingFile((prev) => ({ ...prev, [cacheKey]: true }));
      try {
        const res = await client.get('/documents/content', {
          params: docId ? { doc_id: docId, limit: 30 } : { filepath, limit: 30 },
        });
        setFileContentCache((prev) => ({ ...prev, [cacheKey]: res.data }));
      } catch {} finally {
        setLoadingFile((prev) => ({ ...prev, [cacheKey]: false }));
      }
    }
  };

  const openPdfTab = async (filepath: string, docId?: number | null) => {
    setPreviewError('');
    try {
      await openPdfPreview(filepath, docId ?? undefined);
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : 'Preview unavailable.');
    }
  };

  const handleOpenCitationDoc = (source: string, docId?: number | null) => {
    const docMatch = accessibleDocs.find(
      (d) => (docId && d.id === docId) || d.filename === source
    );
    const filepath = docMatch?.filepath || '';
    const resolvedDocId = docId ?? docMatch?.id;
    if (source.toLowerCase().endsWith('.pdf')) {
      void openPdfTab(filepath, resolvedDocId);
    } else {
      void toggleSource(source, filepath, resolvedDocId);
    }
  };

  const renderSourceContent = (filename: string, filepath: string, docId?: number | null) => {
    const cacheKey = filepath || String(docId || filename);
    const cache = fileContentCache[cacheKey];
    if (loadingFile[cacheKey]) {
      return (
        <div className="source-loading">
          <div className="source-loading-spinner" />
          Loading file content…
        </div>
      );
    }
    if (!cache) {
      return <div className="source-error">⚠️ Content unavailable or access restricted.</div>;
    }
    if (cache.type === 'csv') {
      return (
        <div className="fs-table-wrap" style={{ maxHeight: '260px', marginTop: '8px' }}>
          <table className="fs-table">
            <thead>
              <tr>
                <th>#</th>
                {cache.columns?.map((col: string, i: number) => (
                  <th key={i}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cache.data?.slice(0, 30).map((row: any, rIdx: number) => (
                <tr key={rIdx}>
                  <td>{rIdx + 1}</td>
                  {cache.columns?.map((col: string, cIdx: number) => (
                    <td key={cIdx}>
                      {row[col] === null ? (
                        <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>null</span>
                      ) : (
                        String(row[col])
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
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
              ),
            }}
          >
            {cache.content}
          </ReactMarkdown>
        </div>
      );
    }
    return null;
  };

  const formatTime = (d: Date) =>
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const suggestions = [
    { icon: <FileText size={18} />, text: 'Summarize our employee handbook' },
    {
      icon: <BarChart2 size={18} />,
      text: `Summarize the key findings in ${
        role?.toLowerCase() === 'c-level' ? 'our department' : `our ${role || 'department'}`
      } reports`,
    },
    { icon: <Database size={18} />, text: 'Compare revenue and expenses across structured datasets' },
    { icon: <Sparkles size={18} />, text: 'What are our company leave policies?' },
  ];

  return (
    <div className="chat-shell">
      <ThreadSidebar
        threads={threads}
        activeThreadId={activeThreadId}
        loading={threadsLoading}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
        onNewThread={handleNewThread}
        onSelectThread={handleSelectThread}
        onRenameThread={handleRenameThread}
        onDeleteThread={handleDeleteThread}
      />

      <div className="chat-page-root">
        {previewError && (
          <div className="form-error" role="alert">
            {previewError}
          </div>
        )}

        <div className="chat-page-header">
          <div>
            <h1 className="fs-title" style={{ fontSize: '20px', marginBottom: '2px' }}>
              <Bot size={20} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '8px' }} />
              Agentic AI assistant
            </h1>
            <p className="fs-subtitle">
              ReBAC-governed search, self-correcting SQL analytics & cited answers.{' '}
              <kbd className="kbd">Enter</kbd> to send
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {messages.length > 0 && <span className="chat-msg-count">{messages.length} messages</span>}
            {messages.length > 0 && (
              <button
                type="button"
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

        <div className="chat-window">
          {messages.length === 0 ? (
            <div className="chat-welcome">
              <div className="chat-welcome-icon">
                <Zap size={32} color="var(--primary-hover)" />
              </div>
              <span className="eyebrow" style={{ marginBottom: 14 }}>
                AGENTIC INTELLIGENCE · {role?.toUpperCase() || 'WORKSPACE'}
              </span>
              <h2 className="chat-welcome-title">What would you like to discover?</h2>
              <p className="chat-welcome-sub">
                Welcome, {username || 'there'}. Ask multi-step analytical questions across your
                authorized PDFs, reports, and datasets.
              </p>
              <div className="chat-suggestions-grid">
                {suggestions.map((s, i) => (
                  <button
                    key={i}
                    type="button"
                    className="chat-suggestion-card"
                    onClick={() => void handleSend(s.text)}
                  >
                    <span className="chat-suggestion-icon">{s.icon}</span>
                    <span>{s.text}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat-messages-list">
              {messages.map((msg) => {
                const isAssistant = msg.role === 'assistant';
                const isStreaming = msg.isStreaming === true;
                const isGreeting = msg.mode === 'GREETING';
                const isBlocked = msg.mode === 'BLOCKED';

                return (
                  <div
                    key={msg.id}
                    className={`chat-msg-row ${isAssistant ? 'chat-msg-row--assistant' : 'chat-msg-row--user'}`}
                  >
                    <div
                      className={`chat-msg-avatar ${isAssistant ? 'chat-msg-avatar--ai' : 'chat-msg-avatar--user'}`}
                    >
                      {isAssistant ? <Bot size={16} /> : <UserIcon size={15} />}
                    </div>

                    <div
                      className={`chat-msg-bubble ${isAssistant ? 'chat-msg-bubble--ai' : 'chat-msg-bubble--user'}`}
                    >
                      <div className="chat-msg-meta">
                        <span className="chat-msg-sender">
                          {isAssistant ? 'FinSight AI' : username || 'You'}
                        </span>
                        <span className="chat-msg-time">{formatTime(msg.timestamp)}</span>
                      </div>

                      {isAssistant && msg.agent_steps && msg.agent_steps.length > 0 && (
                        <AgentStepsBar steps={msg.agent_steps} isStreaming={isStreaming} />
                      )}

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
                              ),
                            }}
                          >
                            {msg.content}
                          </ReactMarkdown>
                          {isStreaming && msg.content && <StreamingCursor />}
                        </div>
                      )}

                      {isAssistant && (msg.chart_spec || msg.sql) && (
                        <ChartRenderer chartSpec={msg.chart_spec} sql={msg.sql} />
                      )}

                      {isStreaming && tokenCount > 0 && (
                        <div className="chat-token-counter">{tokenCount} chunks</div>
                      )}

                      {isAssistant && !isStreaming && msg.content && (
                        <div className="chat-msg-actions">
                          <CopyButton text={msg.content} />
                        </div>
                      )}

                      {isAssistant && !isStreaming && !isGreeting && !isBlocked && (
                        <div className="chat-msg-badges">
                          {msg.mode === 'HYBRID' ? (
                            <span className="chat-badge chat-badge--sql">
                              <Database size={10} /> Hybrid SQL + RAG
                            </span>
                          ) : msg.sql ? (
                            <span className="chat-badge chat-badge--sql">
                              <Database size={10} /> Governed DuckDB SQL
                            </span>
                          ) : (
                            <span className="chat-badge chat-badge--rag">
                              <FileText size={10} /> ReBAC Hybrid RAG
                            </span>
                          )}
                          <span className="chat-badge">
                            <ShieldCheck size={10} /> PII & ACL Checked
                          </span>
                          {msg.fallback && (
                            <span className="chat-badge chat-badge--fallback">↩ Fallback</span>
                          )}
                          <span className="ai-disclosure-note">
                            AI-generated answer · Grounded in authorized records
                          </span>
                        </div>
                      )}

                      {isAssistant && !isStreaming && msg.citations && msg.citations.length > 0 && (
                        <div className="citation-chips-row">
                          <span className="citation-chips-label">Citations:</span>
                          {msg.citations.map((cit) => (
                            <button
                              key={`${cit.chunk_id}-${cit.index}`}
                              type="button"
                              className={`citation-chip${
                                selectedCitation?.chunk_id === cit.chunk_id
                                  ? ' citation-chip--active'
                                  : ''
                              }`}
                              onClick={() => setSelectedCitation(cit)}
                            >
                              [{cit.index}] {cit.source}
                              {cit.page_number ? ` p.${cit.page_number}` : ''}
                            </button>
                          ))}
                        </div>
                      )}

                      {isAssistant && !isStreaming && msg.sources && msg.sources.length > 0 && (
                        <div className="chat-sources-section">
                          <div className="chat-sources-title">
                            <CornerDownRight size={12} /> Referenced Sources
                          </div>
                          {msg.sources.map((src, sIdx) => {
                            const docMatch = accessibleDocs.find((d) => d.filename === src);
                            const filepath = docMatch?.filepath || '';
                            const isPdf = src.toLowerCase().endsWith('.pdf');
                            const key = `${src}-${filepath || docMatch?.id || ''}`;
                            const isExpanded = openSources[key] || false;
                            const ext = src.split('.').pop()?.toLowerCase();
                            const icon = ext === 'pdf' ? '📑' : ext === 'csv' ? '📊' : '📄';

                            return (
                              <div key={sIdx} className="chat-source-item">
                                <div
                                  className="chat-source-header"
                                  onClick={() =>
                                    isPdf
                                      ? void openPdfTab(filepath, docMatch?.id)
                                      : void toggleSource(src, filepath, docMatch?.id)
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
                                      {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                                    </span>
                                  )}
                                </div>
                                {isExpanded && !isPdf && (
                                  <div className="chat-source-body">
                                    {renderSourceContent(src, filepath, docMatch?.id)}
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

        <div className="chat-input-area">
          {isSending && (
            <div className="chat-status-row">
              <div className="chat-status-dot" />
              <span>Orchestrating agent steps…</span>
              <button type="button" className="chat-stop-btn" onClick={handleStop}>
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
              type="button"
              className={`chat-send-btn ${isSending ? 'chat-send-btn--sending' : ''}`}
              onClick={() => void handleSend(inputValue)}
              disabled={isSending || !inputValue.trim()}
              title="Send (Enter)"
            >
              <Send size={17} />
            </button>
          </div>

          <div className="chat-input-footer">
            <span>Answers grounded in your authorized documents. Verify citations for decisions.</span>
            {inputValue.length > 0 && (
              <span className="chat-char-count">{inputValue.length} chars</span>
            )}
          </div>
        </div>
      </div>

      <CitationDrawer
        citation={selectedCitation}
        onClose={() => setSelectedCitation(null)}
        onOpenDocument={handleOpenCitationDoc}
      />
    </div>
  );
}
