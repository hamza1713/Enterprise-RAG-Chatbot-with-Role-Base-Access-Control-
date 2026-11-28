import { useState } from 'react';
import type { ChatThread } from '../../types';
import { MessageSquarePlus, PanelLeftClose, PanelLeftOpen, Trash2, Pencil, Check, X, MessageSquare } from 'lucide-react';

interface ThreadSidebarProps {
  threads: ChatThread[];
  activeThreadId: string | null;
  loading: boolean;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNewThread: () => void;
  onSelectThread: (threadId: string) => void;
  onRenameThread: (threadId: string, title: string) => Promise<void>;
  onDeleteThread: (threadId: string) => Promise<void>;
}

export default function ThreadSidebar({
  threads,
  activeThreadId,
  loading,
  collapsed,
  onToggleCollapse,
  onNewThread,
  onSelectThread,
  onRenameThread,
  onDeleteThread,
}: ThreadSidebarProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  if (collapsed) {
    return (
      <div className="thread-sidebar thread-sidebar--collapsed">
        <button
          type="button"
          className="icon-button"
          onClick={onToggleCollapse}
          title="Show conversation history"
          aria-label="Show conversation history"
        >
          <PanelLeftOpen size={17} />
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={onNewThread}
          title="New conversation"
          aria-label="New conversation"
        >
          <MessageSquarePlus size={17} />
        </button>
      </div>
    );
  }

  return (
    <aside className="thread-sidebar" aria-label="Conversations">
      <div className="thread-sidebar-header">
        <button
          type="button"
          className="fs-btn fs-btn-primary thread-new-btn"
          onClick={onNewThread}
        >
          <MessageSquarePlus size={15} />
          <span>New chat</span>
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={onToggleCollapse}
          title="Collapse history"
          aria-label="Collapse history"
        >
          <PanelLeftClose size={16} />
        </button>
      </div>

      <div className="thread-list">
        {loading && threads.length === 0 && (
          <div className="thread-empty">Loading history…</div>
        )}
        {!loading && threads.length === 0 && (
          <div className="thread-empty">Your conversation threads will appear here.</div>
        )}
        {threads.map((t) => {
          const isActive = t.id === activeThreadId;
          const isEditing = editingId === t.id;
          const isConfirming = confirmDeleteId === t.id;

          return (
            <div
              key={t.id}
              className={`thread-item${isActive ? ' thread-item--active' : ''}`}
            >
              {isEditing ? (
                <div className="thread-edit-row">
                  <input
                    className="fs-input thread-edit-input"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    maxLength={160}
                    autoFocus
                    onKeyDown={async (e) => {
                      if (e.key === 'Enter' && editTitle.trim()) {
                        await onRenameThread(t.id, editTitle.trim());
                        setEditingId(null);
                      } else if (e.key === 'Escape') {
                        setEditingId(null);
                      }
                    }}
                  />
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="Save title"
                    onClick={async () => {
                      if (editTitle.trim()) {
                        await onRenameThread(t.id, editTitle.trim());
                      }
                      setEditingId(null);
                    }}
                  >
                    <Check size={13} />
                  </button>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="Cancel rename"
                    onClick={() => setEditingId(null)}
                  >
                    <X size={13} />
                  </button>
                </div>
              ) : (
                <>
                  <button
                    type="button"
                    className="thread-item-btn"
                    onClick={() => onSelectThread(t.id)}
                    title={t.title}
                  >
                    <MessageSquare size={13} />
                    <span>{t.title}</span>
                  </button>
                  <div className="thread-item-actions">
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={`Rename ${t.title}`}
                      onClick={() => {
                        setEditingId(t.id);
                        setEditTitle(t.title);
                        setConfirmDeleteId(null);
                      }}
                    >
                      <Pencil size={12} />
                    </button>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={isConfirming ? `Confirm delete ${t.title}` : `Delete ${t.title}`}
                      onClick={async () => {
                        if (!isConfirming) {
                          setConfirmDeleteId(t.id);
                          return;
                        }
                        await onDeleteThread(t.id);
                        setConfirmDeleteId(null);
                      }}
                    >
                      {isConfirming ? <Check size={12} color="#fca5a5" /> : <Trash2 size={12} />}
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
