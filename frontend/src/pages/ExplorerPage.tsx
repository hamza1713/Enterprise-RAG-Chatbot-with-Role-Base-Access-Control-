import React, { useState, useEffect, useRef, useCallback } from 'react';
import client from '../api/client';
import { deleteDocument, openPdfPreview, updateDocumentRole } from '../api/documents';
import { fetchRoles } from '../api/admin';
import { useAuthStore } from '../store/authStore';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  FolderOpen,
  Search,
  SlidersHorizontal,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ExternalLink,
  RefreshCw,
  Trash2,
} from 'lucide-react';

interface DocInfo {
  id?: number;
  filename: string;
  filepath: string;
  role?: string;
}

export default function ExplorerPage() {
  const userRole = useAuthStore((s) => s.role);
  const isAdmin = userRole?.toLowerCase() === 'c-level';

  const [listError, setListError] = useState('');
  const [actionBanner, setActionBanner] = useState<string | null>(null);
  const [documents, setDocuments] = useState<DocInfo[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<string>('');
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [loadingContent, setLoadingContent] = useState(false);
  const [mutatingDoc, setMutatingDoc] = useState(false);
  const [confirmDeleteSelected, setConfirmDeleteSelected] = useState(false);

  // Current document content
  const [docContent, setDocContent] = useState<any>(null);

  // CSV Grid Specific States
  const [searchQuery, setSearchQuery] = useState('');
  const [columnFilters, setColumnFilters] = useState<Record<string, string>>({});
  const [selectedFilterCol, setSelectedFilterCol] = useState('');
  const [filterVal, setFilterVal] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [showFiltersPanel, setShowFiltersPanel] = useState(false);
  const [csvOffset, setCsvOffset] = useState(0);
  const sliceAbortRef = useRef<AbortController | null>(null);

  const loadCsvSlice = async (doc: DocInfo, newOffset: number) => {
    sliceAbortRef.current?.abort();
    const controller = new AbortController();
    sliceAbortRef.current = controller;
    setLoadingContent(true);
    try {
      const res = await client.get('/documents/content', {
        params:
          doc.id !== undefined
            ? { doc_id: doc.id, filepath: doc.filepath, limit: 500, offset: Math.max(0, newOffset) }
            : { filepath: doc.filepath, limit: 500, offset: Math.max(0, newOffset) },
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setCsvOffset(Math.max(0, newOffset));
      setDocContent(res.data);
      setCurrentPage(1);
    } catch (e) {
      if (controller.signal.aborted) return;
      console.error('Failed to load CSV slice', e);
      setDocContent({ type: 'error', message: 'Failed to retrieve file slice.' });
    } finally {
      if (!controller.signal.aborted) setLoadingContent(false);
    }
  };

  // Fetch document lists
  const fetchDocList = useCallback(async () => {
    setLoadingDocs(true);
    setListError('');
    try {
      const res = await client.get('/documents');
      setDocuments(res.data);
      setSelectedDoc('');
      setConfirmDeleteSelected(false);
      if (isAdmin) {
        const rolesData = await fetchRoles();
        setRoles(rolesData.roles || []);
      }
    } catch (e) {
      console.error('Failed to fetch documents', e);
      setListError('Documents could not be loaded. Check your connection and choose Refresh.');
    } finally {
      setLoadingDocs(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    void fetchDocList();
  }, [fetchDocList]);

  // Fetch content on doc selection
  useEffect(() => {
    const controller = new AbortController();
    setLoadingContent(false);
    if (!selectedDoc) {
      setDocContent(null);
      return;
    }

    const doc = documents.find((d) => d.filepath === selectedDoc);
    if (!doc) return;

    if (doc.filename.toLowerCase().endsWith('.pdf') || selectedDoc.toLowerCase().endsWith('.pdf')) {
      setDocContent({ type: 'pdf', filepath: doc.filepath, id: doc.id });
      return;
    }

    const fetchContent = async () => {
      setLoadingContent(true);
      try {
        const res = await client.get('/documents/content', {
          params:
            doc.id !== undefined
              ? { doc_id: doc.id, filepath: doc.filepath, limit: 500, offset: 0 }
              : { filepath: doc.filepath, limit: 500, offset: 0 },
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setCsvOffset(0);
        setDocContent(res.data);
        setSearchQuery('');
        setColumnFilters({});
        setSelectedFilterCol('');
        setFilterVal('');
        setCurrentPage(1);
      } catch (e) {
        if (controller.signal.aborted) return;
        console.error('Failed to load document content', e);
        setDocContent({ type: 'error', message: 'Failed to retrieve file contents.' });
      } finally {
        if (!controller.signal.aborted) setLoadingContent(false);
      }
    };

    void fetchContent();
    return () => controller.abort();
  }, [selectedDoc, documents]);

  const activeDocRecord = documents.find((d) => d.filepath === selectedDoc);

  const handleOpenPdf = async (filepath: string, docId?: number) => {
    setListError('');
    try {
      await openPdfPreview(filepath, docId);
    } catch (error) {
      setListError(error instanceof Error ? error.message : 'Preview unavailable.');
    }
  };

  const handleReassignRole = async (newRole: string) => {
    if (!activeDocRecord?.id || newRole === activeDocRecord.role) return;
    setMutatingDoc(true);
    setListError('');
    setActionBanner(null);
    try {
      const res = await updateDocumentRole(activeDocRecord.id, newRole);
      setDocuments((prev) =>
        prev.map((d) => (d.id === activeDocRecord.id ? { ...d, role: res.role } : d)),
      );
      setActionBanner(res.message || `Reassigned '${activeDocRecord.filename}' to '${res.role}'.`);
    } catch (e: any) {
      setListError(e.response?.data?.detail || 'Failed to reassign document role.');
    } finally {
      setMutatingDoc(false);
    }
  };

  const handleDeleteSelectedDoc = async () => {
    if (!activeDocRecord?.id) return;
    if (!confirmDeleteSelected) {
      setConfirmDeleteSelected(true);
      setActionBanner(
        `Click Delete again to remove '${activeDocRecord.filename}' from library and vector index.`,
      );
      return;
    }
    setMutatingDoc(true);
    setConfirmDeleteSelected(false);
    setListError('');
    setActionBanner(null);
    try {
      const res = await deleteDocument(activeDocRecord.id);
      setActionBanner(res.message || `Deleted '${activeDocRecord.filename}'.`);
      setSelectedDoc('');
      setDocContent(null);
      await fetchDocList();
    } catch (e: any) {
      setListError(e.response?.data?.detail || 'Failed to delete document.');
    } finally {
      setMutatingDoc(false);
    }
  };

  const applyColumnFilter = () => {
    if (!selectedFilterCol || !filterVal.trim()) return;
    setColumnFilters((prev) => ({
      ...prev,
      [selectedFilterCol]: filterVal.trim(),
    }));
    setFilterVal('');
    setCurrentPage(1);
  };

  const removeColumnFilter = (col: string) => {
    setColumnFilters((prev) => {
      const next = { ...prev };
      delete next[col];
      return next;
    });
    setCurrentPage(1);
  };

  const getFilteredRows = () => {
    if (!docContent || docContent.type !== 'csv' || !docContent.data) return [];

    let rows = [...docContent.data];

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      rows = rows.filter((row) =>
        Object.values(row).some((val) => String(val ?? '').toLowerCase().includes(q)),
      );
    }

    Object.entries(columnFilters).forEach(([col, filterText]) => {
      const f = filterText.toLowerCase().trim();
      rows = rows.filter((row) => String(row[col] ?? '').toLowerCase().includes(f));
    });

    return rows;
  };

  const filteredRows = getFilteredRows();
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));

  const paginatedRows = (() => {
    const start = (currentPage - 1) * pageSize;
    return filteredRows.slice(start, start + pageSize);
  })();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {listError && (
        <div className="form-error" role="alert">
          {listError}
        </div>
      )}
      {actionBanner && (
        <div
          style={{
            marginBottom: '12px',
            padding: '10px 14px',
            borderRadius: 'var(--radius-sm)',
            background: 'rgba(16, 185, 129, 0.14)',
            border: '1px solid rgba(16, 185, 129, 0.28)',
            color: '#34D399',
            fontSize: '13px',
          }}
        >
          {actionBanner}
        </div>
      )}
      {/* Header */}
      <div
        className="fs-header"
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
      >
        <div>
          <h1 className="fs-title">Document library</h1>
          <p className="fs-subtitle">
            Browse, search, and preview CSV sheets and Markdown guides indexed in your role workspace.
          </p>
        </div>
        <button
          className="fs-btn fs-btn-secondary"
          style={{ padding: '8px 12px' }}
          onClick={() => void fetchDocList()}
          disabled={loadingDocs}
        >
          <RefreshCw size={14} className={loadingDocs ? 'animate-spin' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Select Box Grid */}
      <div className="fs-card" style={{ padding: '18px 24px', marginBottom: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
          <FolderOpen size={20} color="var(--primary)" />
          <div style={{ flex: 1, maxWidth: '380px', minWidth: '220px' }}>
            <select
              className="fs-input"
              value={selectedDoc}
              onChange={(e) => {
                setSelectedDoc(e.target.value);
                setConfirmDeleteSelected(false);
                setActionBanner(null);
              }}
              disabled={loadingDocs}
              style={{ paddingRight: '36px' }}
            >
              <option value="">— Select a document —</option>
              {documents.map((doc, idx) => (
                <option key={doc.id ?? idx} value={doc.filepath}>
                  {doc.filename} {doc.role ? `(${doc.role})` : ''}
                </option>
              ))}
            </select>
          </div>

          {isAdmin && activeDocRecord?.id !== undefined && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginLeft: 'auto', flexWrap: 'wrap' }}>
              <select
                className="fs-input"
                aria-label="Reassign document role"
                value={activeDocRecord.role || ''}
                disabled={mutatingDoc || roles.length === 0}
                onChange={(e) => handleReassignRole(e.target.value)}
                style={{ width: '150px', height: '36px', padding: '0 8px', fontSize: '12.5px' }}
              >
                {roles.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="fs-btn fs-btn-danger"
                style={{ height: '36px', padding: '0 12px', fontSize: '12.5px' }}
                disabled={mutatingDoc}
                onClick={handleDeleteSelectedDoc}
              >
                <Trash2 size={14} />
                <span>{confirmDeleteSelected ? 'Confirm Delete' : 'Delete Document'}</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Render Area */}
      <div
        className="fs-card"
        style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', padding: 0 }}
      >
        {loadingContent ? (
          <div style={loadingCenterStyle}>
            <div className="chat-thinking">
              <span></span>
              <span></span>
              <span></span>
              <span style={{ marginLeft: '6px' }}>Loading document data…</span>
            </div>
          </div>
        ) : !selectedDoc ? (
          <div className="fs-empty-state" style={{ margin: 'auto' }}>
            <div className="fs-empty-icon">📄</div>
            <div className="fs-empty-title">No document selected</div>
            <p className="fs-empty-sub">
              Choose a document from the dropdown above to load interactive data views, text guides, or PDF logs.
            </p>
          </div>
        ) : docContent?.type === 'pdf' ? (
          <div style={pdfSplashStyle}>
            <div style={pdfIconContainerStyle}>📑</div>
            <h3 style={{ fontSize: '18px', fontWeight: 700, marginBottom: '8px' }}>PDF File Selected</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '13.5px', marginBottom: '20px', maxWidth: '350px' }}>
              For optimal rendering, PDF previews open in your browser's native viewer.
            </p>
            <button
              className="fs-btn fs-btn-primary"
              onClick={() => handleOpenPdf(docContent.filepath, docContent.id)}
            >
              <ExternalLink size={15} />
              <span>Open PDF in New Tab</span>
            </button>
          </div>
        ) : docContent?.type === 'markdown' ? (
          <div style={{ overflowY: 'auto', padding: '32px', textAlign: 'left' }}>
            <div className="chat-message-content">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  table: ({ node: _node, ...props }) => (
                    <div className="fs-table-wrap" style={{ margin: '14px 0' }}>
                      <table className="fs-table" {...props} />
                    </div>
                  ),
                }}
              >
                {docContent.content}
              </ReactMarkdown>
            </div>
          </div>
        ) : docContent?.type === 'csv' ? (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '100%' }}>
            <div style={gridControlPanelStyle}>
              <div style={gridControlHeaderStyle}>
                <div style={{ position: 'relative', flex: 1, maxWidth: '320px' }}>
                  <input
                    type="text"
                    className="fs-input"
                    placeholder="🔍 Search all cells..."
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value);
                      setCurrentPage(1);
                    }}
                    style={{ paddingLeft: '38px', height: '36px', fontSize: '13px' }}
                  />
                  <Search size={14} style={searchIconPositionStyle} />
                </div>

                <button
                  className="fs-btn fs-btn-secondary"
                  style={{ height: '36px', padding: '0 14px', fontSize: '13px', display: 'flex', gap: '6px' }}
                  onClick={() => setShowFiltersPanel(!showFiltersPanel)}
                >
                  <SlidersHorizontal size={14} />
                  <span>
                    Column Filters{' '}
                    {Object.keys(columnFilters).length > 0 && `(${Object.keys(columnFilters).length})`}
                  </span>
                </button>
              </div>

              {showFiltersPanel && (
                <div style={filterPanelGridStyle}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <select
                      className="fs-input"
                      value={selectedFilterCol}
                      onChange={(e) => setSelectedFilterCol(e.target.value)}
                      style={{ width: '160px', height: '34px', padding: '0 8px', fontSize: '13px' }}
                    >
                      <option value="">Select Column</option>
                      {docContent.columns?.map((col: string, idx: number) => (
                        <option key={idx} value={col}>
                          {col}
                        </option>
                      ))}
                    </select>

                    <input
                      type="text"
                      className="fs-input"
                      placeholder="Filter value..."
                      value={filterVal}
                      onChange={(e) => setFilterVal(e.target.value)}
                      style={{ width: '180px', height: '34px', fontSize: '13px' }}
                      onKeyDown={(e) => e.key === 'Enter' && applyColumnFilter()}
                    />

                    <button
                      className="fs-btn fs-btn-primary"
                      style={{ height: '34px', padding: '0 12px', fontSize: '13px' }}
                      onClick={applyColumnFilter}
                    >
                      Apply
                    </button>
                  </div>

                  {Object.keys(columnFilters).length > 0 && (
                    <div style={filterTagsContainerStyle}>
                      {Object.entries(columnFilters).map(([col, text], idx) => (
                        <div key={idx} style={filterTagStyle}>
                          <span>
                            <b>{col}</b>: {text}
                          </span>
                          <span style={removeTagBtnStyle} onClick={() => removeColumnFilter(col)}>
                            ×
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {(docContent.truncated || csvOffset > 0) && activeDocRecord && (
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  fontSize: '12px',
                  color: 'var(--text-secondary)',
                  background: 'rgba(94, 157, 128, 0.08)',
                  borderBottom: '1px solid rgba(94, 157, 128, 0.2)',
                  padding: '6px 24px',
                }}
              >
                <span>
                  Server slice: rows{' '}
                  <b>
                    {(docContent.offset ?? csvOffset) + 1}–
                    {(docContent.offset ?? csvOffset) + (docContent.data?.length ?? 0)}
                  </b>{' '}
                  of <b>{docContent.total_rows ?? docContent.data?.length}</b>
                </span>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    className="fs-btn fs-btn-secondary"
                    style={{ height: '26px', padding: '0 10px', fontSize: '12px' }}
                    disabled={(docContent.offset ?? csvOffset) <= 0 || loadingContent}
                    onClick={() =>
                      loadCsvSlice(activeDocRecord, Math.max(0, (docContent.offset ?? csvOffset) - 500))
                    }
                  >
                    Prev 500
                  </button>
                  <button
                    className="fs-btn fs-btn-secondary"
                    style={{ height: '26px', padding: '0 10px', fontSize: '12px' }}
                    disabled={!docContent.truncated || loadingContent}
                    onClick={() =>
                      loadCsvSlice(
                        activeDocRecord,
                        (docContent.offset ?? csvOffset) + (docContent.limit ?? 500),
                      )
                    }
                  >
                    Next 500
                  </button>
                </div>
              </div>
            )}
            <div className="fs-table-wrap" style={{ flex: 1, borderRadius: 0, border: 'none', margin: 0 }}>
              <table className="fs-table">
                <thead>
                  <tr>
                    <th
                      style={{
                        width: '50px',
                        minWidth: '50px',
                        textAlign: 'center',
                        background: '#233331',
                        color: 'var(--primary-hover)',
                        fontWeight: 'bold',
                        position: 'sticky',
                        left: 0,
                        zIndex: 12,
                      }}
                    >
                      #
                    </th>
                    {docContent.columns?.map((col: string, idx: number) => (
                      <th key={idx}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {paginatedRows.length === 0 ? (
                    <tr>
                      <td
                        colSpan={(docContent.columns?.length || 0) + 1}
                        style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}
                      >
                        No records match the current filters.
                      </td>
                    </tr>
                  ) : (
                    paginatedRows.map((row: any, rIdx: number) => (
                      <tr key={rIdx}>
                        <td
                          style={{
                            textAlign: 'center',
                            background: 'rgba(94,157,128, 0.05)',
                            fontWeight: 'bold',
                            color: 'var(--text-muted)',
                            position: 'sticky',
                            left: 0,
                            zIndex: 5,
                            borderRight: '1px solid rgba(94,157,128, 0.15)',
                          }}
                        >
                          {(currentPage - 1) * pageSize + rIdx + 1}
                        </td>
                        {docContent.columns?.map((col: string, cIdx: number) => (
                          <td key={cIdx}>
                            {row[col] === null ? (
                              <span style={{ color: 'var(--text-muted)' }}>null</span>
                            ) : (
                              String(row[col])
                            )}
                          </td>
                        ))}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div style={paginationFooterStyle}>
              <div style={{ color: 'var(--text-muted)' }}>
                Showing{' '}
                <b>
                  {Math.min(filteredRows.length, (currentPage - 1) * pageSize + 1)}-
                  {Math.min(filteredRows.length, currentPage * pageSize)}
                </b>{' '}
                of <b>{filteredRows.length}</b> rows
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Size:</span>
                  <select
                    className="fs-input"
                    value={pageSize}
                    onChange={(e) => {
                      setPageSize(Number(e.target.value));
                      setCurrentPage(1);
                    }}
                    style={{ width: '70px', height: '28px', padding: '0 4px', fontSize: '12px' }}
                  >
                    {[10, 25, 50, 100, 250, 500].map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <button
                    className="fs-btn fs-btn-secondary"
                    style={pageBtnStyle}
                    onClick={() => setCurrentPage(1)}
                    disabled={currentPage === 1}
                  >
                    <ChevronsLeft size={14} />
                  </button>
                  <button
                    className="fs-btn fs-btn-secondary"
                    style={pageBtnStyle}
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    disabled={currentPage === 1}
                  >
                    <ChevronLeft size={14} />
                  </button>
                  <span style={{ fontSize: '13px', color: 'var(--text-secondary)', padding: '0 8px' }}>
                    Page <b>{currentPage}</b> of {totalPages}
                  </span>
                  <button
                    className="fs-btn fs-btn-secondary"
                    style={pageBtnStyle}
                    onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                    disabled={currentPage === totalPages}
                  >
                    <ChevronRight size={14} />
                  </button>
                  <button
                    className="fs-btn fs-btn-secondary"
                    style={pageBtnStyle}
                    onClick={() => setCurrentPage(totalPages)}
                    disabled={currentPage === totalPages}
                  >
                    <ChevronsRight size={14} />
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : docContent?.type === 'error' ? (
          <div className="fs-empty-state" style={{ margin: 'auto' }}>
            <div className="fs-empty-icon">⚠️</div>
            <div className="fs-empty-title">Error Loading File</div>
            <p className="fs-empty-sub">{docContent.message}</p>
          </div>
        ) : null}
      </div>
    </div>
  );
}

const loadingCenterStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  height: '100%',
  width: '100%',
};

const pdfSplashStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  textAlign: 'center',
  height: '100%',
  width: '100%',
  padding: '40px',
  background: 'rgba(13,23,25, 0.25)',
};

const pdfIconContainerStyle: React.CSSProperties = {
  fontSize: '60px',
  marginBottom: '16px',
  width: '100px',
  height: '100px',
  borderRadius: '50%',
  background: 'rgba(94,157,128, 0.1)',
  border: '1px solid var(--border)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  boxShadow: '0 8px 24px rgba(0,0,0,0.2)',
};

const gridControlPanelStyle: React.CSSProperties = {
  background: 'rgba(22,34,37, 0.45)',
  borderBottom: '1px solid var(--border)',
  padding: '12px 24px',
  display: 'flex',
  flexDirection: 'column',
  gap: '12px',
};

const gridControlHeaderStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  gap: '16px',
};

const searchIconPositionStyle: React.CSSProperties = {
  position: 'absolute',
  left: '14px',
  top: '50%',
  transform: 'translateY(-50%)',
  color: 'var(--text-muted)',
};

const filterPanelGridStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '8px',
  padding: '10px',
  background: 'rgba(13,23,25, 0.3)',
  border: '1px solid rgba(255, 255, 255, 0.03)',
  borderRadius: 'var(--radius-sm)',
};

const filterTagsContainerStyle: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: '6px',
  marginTop: '4px',
};

const filterTagStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '8px',
  padding: '4px 10px',
  background: 'rgba(94,157,128, 0.1)',
  border: '1px solid rgba(94,157,128, 0.25)',
  borderRadius: '4px',
  fontSize: '11.5px',
  color: 'var(--text-secondary)',
};

const removeTagBtnStyle: React.CSSProperties = {
  cursor: 'pointer',
  fontWeight: 'bold',
  color: 'red',
  fontSize: '14px',
  padding: '0 2px',
};

const paginationFooterStyle: React.CSSProperties = {
  background: 'rgba(22,34,37, 0.85)',
  borderTop: '1px solid var(--border)',
  padding: '12px 24px',
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  fontSize: '13px',
};

const pageBtnStyle: React.CSSProperties = {
  width: '32px',
  height: '32px',
  padding: 0,
};
