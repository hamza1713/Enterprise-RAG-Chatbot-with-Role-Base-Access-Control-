import React, { useState, useEffect } from 'react';
import client from '../api/client';
import type { BulkStatusResponse, DocIndexingDetail } from '../types';
import {
  CheckCircle,
  RefreshCw,
  AlertTriangle,
  RotateCcw,
  Search,
} from 'lucide-react';

export default function KbIndexingPage() {
  const [bulkData, setBulkData] = useState<BulkStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [confirmReindex, setConfirmReindex] = useState(false);
  const [confirmMsg, setConfirmMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState('All');
  const [searchTerm, setSearchTerm] = useState('');

  const fetchStatus = async (showLoader = true) => {
    if (showLoader) setLoading(true);
    try {
      const res = await client.get('/indexing-status-bulk');
      setBulkData(res.data);
    } catch (e) {
      console.error('Failed to fetch bulk indexing status', e);
    } finally {
      if (showLoader) setLoading(false);
    }
  };

  // Initial fetch on mount
  useEffect(() => {
    fetchStatus();
  }, []);

  // Auto-refresh loop when there is at least one pending document
  useEffect(() => {
    const summary = bulkData?.summary;
    const hasPending = summary && summary.pending > 0;

    if (!hasPending) return;

    const interval = setInterval(() => {
      fetchStatus(false);
    }, 5000);

    return () => clearInterval(interval);
  }, [bulkData]);

  const handleRetry = async () => {
    setActionLoading(true);
    setSuccessMsg(null);
    setConfirmMsg(null);
    try {
      const res = await client.post('/reindex-retry');
      setSuccessMsg(res.data.message || 'Retry started successfully.');
      setTimeout(() => {
        setSuccessMsg(null);
        fetchStatus(false);
      }, 3000);
    } catch (e: any) {
      console.error('Retry failed', e);
      setConfirmMsg(e.response?.data?.detail || 'Retry failed. Check backend logs.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleReindex = async () => {
    if (!confirmReindex) {
      setConfirmReindex(true);
      setConfirmMsg('⚠️ Confirm full re-index — this wipes ALL vector embeddings and re-processes every document from scratch. Click again to confirm.');
      return;
    }

    setActionLoading(true);
    setSuccessMsg(null);
    setConfirmMsg(null);
    setConfirmReindex(false);
    try {
      const res = await client.post('/reindex');
      setSuccessMsg(res.data.message || 'Full re-index started successfully.');
      setTimeout(() => {
        setSuccessMsg(null);
        fetchStatus(false);
      }, 3000);
    } catch (e: any) {
      console.error('Full re-index failed', e);
      setConfirmMsg(e.response?.data?.detail || 'Failed to wipe and re-index. Check logs.');
    } finally {
      setActionLoading(false);
    }
  };

  // Reset confirmation state on action exit
  useEffect(() => {
    if (confirmReindex) {
      const timer = setTimeout(() => {
        setConfirmReindex(false);
        setConfirmMsg(null);
      }, 8000);
      return () => clearTimeout(timer);
    }
  }, [confirmReindex]);

  const getStatusBadge = (status: DocIndexingDetail['status']) => {
    switch (status) {
      case 'indexed':
        return <span className="fs-badge fs-badge-success">✅ Indexed</span>;
      case 'pending':
        return <span className="fs-badge fs-badge-warning">⏳ Pending</span>;
      case 'failed':
        return <span className="fs-badge fs-badge-danger">❌ Failed</span>;
      default:
        return <span className="fs-badge">❓ Unknown</span>;
    }
  };

  const getProgressBarColor = (status: DocIndexingDetail['status']) => {
    if (status === 'indexed') return '#10B981';
    if (status === 'pending') return '#F59E0B';
    return '#EF4444';
  };

  const getRoleColor = (roleStr: string) => {
    const r = roleStr.toLowerCase();
    if (r === 'c-level') return '#F59E0B';
    if (r === 'hr') return '#10B981';
    if (r === 'finance') return '#3B82F6';
    if (r === 'engineering') return '#A78BFA';
    if (r === 'marketing') return '#EC4899';
    return '#64748B';
  };

  const summary = bulkData?.summary || { total: 0, done: 0, failed: 0, pending: 0, complete: false };
  const allDocs = bulkData?.documents || [];
  const pct = summary.total > 0 ? Math.floor((summary.done / summary.total) * 100) : 0;

  // Filter docs
  const filteredDocs = allDocs.filter(doc => {
    const matchesStatus = statusFilter === 'All' || 
      (statusFilter === '✅ Indexed' && doc.status === 'indexed') ||
      (statusFilter === '⏳ Pending' && doc.status === 'pending') ||
      (statusFilter === '❌ Failed' && doc.status === 'failed');

    const matchesSearch = !searchTerm || doc.filename.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesStatus && matchesSearch;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', paddingBottom: '32px' }}>
      {/* Header */}
      <div className="fs-header">
        <h1 className="fs-title">🗂️ Knowledge Base — Indexing Status</h1>
        <p className="fs-subtitle">Monitor, retry, and manage the document indexing pipeline in real time.</p>
      </div>

      {/* Info Banner */}
      <div style={infoBannerStyle}>
        <div style={{ display: 'flex', gap: '12px' }}>
          <span style={{ fontSize: '20px' }}>💡</span>
          <div>
            <div style={infoTitleStyle}>How indexing works</div>
            <p style={infoTextStyle}>
              Documents are split into chunks and embedded into the vector store for RAG retrieval.
              Use <b>Retry failed/pending</b> to resume after a quota error without re-embedding
              already-indexed docs. Use <b>Re-index all</b> to wipe and rebuild from scratch.
            </p>
          </div>
        </div>
      </div>

      {/* 4 Summary Cards */}
      <div style={summaryGridStyle}>
        <div style={summaryCardStyle('#818CF8')}>
          <div style={summaryIconStyle('#818CF8')}>📁</div>
          <div>
            <div style={summaryLabelStyle}>Total Docs</div>
            <div style={summaryValueStyle('#818CF8')}>{summary.total}</div>
          </div>
        </div>

        <div style={summaryCardStyle('#10B981')}>
          <div style={summaryIconStyle('#10B981')}>✅</div>
          <div>
            <div style={summaryLabelStyle}>Indexed</div>
            <div style={summaryValueStyle('#10B981')}>{summary.done}</div>
          </div>
        </div>

        <div style={summaryCardStyle('#F59E0B')}>
          <div style={summaryIconStyle('#F59E0B')}>⏳</div>
          <div>
            <div style={summaryLabelStyle}>Pending</div>
            <div style={summaryValueStyle('#F59E0B')}>{summary.pending}</div>
          </div>
        </div>

        <div style={summaryCardStyle('#EF4444')}>
          <div style={summaryIconStyle('#EF4444')}>❌</div>
          <div>
            <div style={summaryLabelStyle}>Failed</div>
            <div style={summaryValueStyle('#EF4444')}>{summary.failed}</div>
          </div>
        </div>
      </div>

      {/* Progress Track Section */}
      <div className="fs-card" style={progressCardStyle}>
        <div style={progressCardHeaderStyle}>
          {summary.pending > 0 ? (
            <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>
              🔄 Indexing in progress… {summary.done}/{summary.total} done ({pct}%)
            </span>
          ) : summary.done === summary.total && summary.total > 0 && summary.failed === 0 ? (
            <span style={{ color: '#10B981', fontWeight: 600 }}>
              ✅ All {summary.total} documents indexed successfully
            </span>
          ) : summary.failed > 0 && summary.pending === 0 ? (
            <span style={{ color: '#EF4444', fontWeight: 600 }}>
              ⚠️ {summary.done} indexed · {summary.failed} failed — click Retry below
            </span>
          ) : (
            <span style={{ color: 'var(--text-muted)' }}>No documents — upload files to begin.</span>
          )}
        </div>
        
        <div className="progress-bar-track" style={{ height: '8px' }}>
          <div
            className="progress-bar-fill"
            style={{
              width: `${pct}%`,
              background: summary.pending > 0 
                ? 'linear-gradient(90deg, var(--primary), var(--secondary))'
                : summary.failed > 0 && summary.pending === 0 ? '#EF4444' : '#10B981'
            }}
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '6px', fontSize: '11px', color: 'var(--text-muted)' }}>
          <span>0%</span>
          <span><b>{pct}%</b></span>
          <span>100%</span>
        </div>

        {summary.pending > 0 && (
          <div style={pollingIndicatorStyle}>
            🔄 Auto-refreshing every 5 seconds while indexing…
          </div>
        )}
      </div>

      {/* Action Buttons panel */}
      <div style={actionRowStyle}>
        <button
          className="fs-btn fs-btn-secondary"
          onClick={handleRetry}
          disabled={actionLoading || summary.pending > 0}
          style={{ height: '40px' }}
        >
          <RotateCcw size={14} />
          <span>Retry Failed / Pending</span>
        </button>

        <button
          className="fs-btn fs-btn-danger"
          onClick={handleReindex}
          disabled={actionLoading}
          style={{ height: '40px' }}
        >
          <RefreshCw size={14} />
          <span>Re-index All (Wipe & Rebuild)</span>
        </button>

        <button
          className="fs-btn fs-btn-secondary"
          onClick={() => fetchStatus(true)}
          disabled={actionLoading}
          style={{ height: '40px', marginLeft: 'auto' }}
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Confirmation & Toast Banner */}
      {confirmMsg && (
        <div style={confirmBannerStyle}>
          <AlertTriangle size={16} />
          <span>{confirmMsg}</span>
        </div>
      )}

      {successMsg && (
        <div style={successBannerStyle}>
          <CheckCircle size={16} />
          <span>{successMsg}</span>
        </div>
      )}

      <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '14px 0' }} />

      {/* Per Document Table */}
      <div className="fs-card" style={{ display: 'flex', flexDirection: 'column', padding: 0, overflow: 'hidden' }}>
        {/* Table Filters header */}
        <div style={tableControlsRowStyle}>
          <h3 style={{ fontSize: '14px', fontWeight: 700 }}>📋 Document Indexing Details</h3>

          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <select
              className="fs-input"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              style={{ width: '130px', height: '32px', padding: '0 8px', fontSize: '12.5px' }}
            >
              <option value="All">All Statuses</option>
              <option value="✅ Indexed">Indexed</option>
              <option value="⏳ Pending">Pending</option>
              <option value="❌ Failed">Failed</option>
            </select>

            <div style={{ position: 'relative' }}>
              <input
                type="text"
                className="fs-input"
                placeholder="Search document name..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={{ width: '200px', height: '32px', paddingLeft: '32px', fontSize: '12.5px' }}
              />
              <Search size={13} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            </div>
          </div>
        </div>

        {/* The Grid Table */}
        <div className="fs-table-wrap" style={{ border: 'none', borderRadius: 0, margin: 0, maxHeight: '420px', overflowY: 'auto' }}>
          <table className="fs-table">
            <thead>
              <tr>
                <th style={{ width: '50px', minWidth: '50px', textAlign: 'center', background: '#0f1330', color: 'var(--primary-hover)', fontWeight: 'bold', position: 'sticky', left: 0, zIndex: 12 }}>#</th>
                <th>Document</th>
                <th>Role</th>
                <th>Status</th>
                <th>Chunk Progress</th>
              </tr>
            </thead>
            <tbody>
              {filteredDocs.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                    {allDocs.length === 0 ? 'No documents ingested yet.' : 'No records match filter parameters.'}
                  </td>
                </tr>
              ) : (
                filteredDocs.map((doc, idx) => {
                  const prog = doc.total_chunks > 0 ? `${doc.embedded_chunks}/${doc.total_chunks}` : '—';
                  const rowPct = doc.total_chunks > 0 ? Math.floor((doc.embedded_chunks / doc.total_chunks) * 100) : 0;
                  return (
                    <tr key={doc.id || idx}>
                      <td style={{ textAlign: 'center', background: 'rgba(99, 102, 241, 0.05)', fontWeight: 'bold', color: 'var(--text-muted)', position: 'sticky', left: 0, zIndex: 5, borderRight: '1px solid rgba(99, 102, 241, 0.15)' }}>
                        {idx + 1}
                      </td>
                      <td style={{ color: '#E2E8F0', maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={doc.filename}>
                        {doc.filename}
                      </td>
                      <td>
                        <span style={{ color: getRoleColor(doc.role), fontWeight: 700 }}>{doc.role}</span>
                      </td>
                      <td>{getStatusBadge(doc.status)}</td>
                      <td style={{ minWidth: '150px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10.5px', color: 'var(--text-muted)', marginBottom: '3px' }}>
                          <span>{prog} chunks</span>
                          <span>{rowPct}%</span>
                        </div>
                        <div className="progress-bar-track">
                          <div
                            className="progress-bar-fill"
                            style={{
                              width: `${rowPct}%`,
                              background: getProgressBarColor(doc.status)
                            }}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Count footer */}
        <div style={tableFooterStyle}>
          Showing {filteredDocs.length} of {allDocs.length} documents
        </div>
      </div>
    </div>
  );
}

// Inline CSS variables
const infoBannerStyle: React.CSSProperties = {
  background: 'rgba(99, 102, 241, 0.05)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-md)',
  padding: '16px 20px',
  marginBottom: '20px',
};

const infoTitleStyle: React.CSSProperties = {
  fontSize: '13.5px',
  fontWeight: 700,
  color: '#F8FAFC',
  marginBottom: '4px',
};

const infoTextStyle: React.CSSProperties = {
  fontSize: '12px',
  color: '#94A3B8',
  lineHeight: '1.6',
};

const summaryGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(4, 1fr)',
  gap: '16px',
  marginBottom: '20px',
};

const summaryCardStyle = (_color: string): React.CSSProperties => ({
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-md)',
  padding: '16px',
  display: 'flex',
  alignItems: 'center',
  gap: '16px',
  boxShadow: '0 4px 14px rgba(0,0,0,0.15)',
});

const summaryIconStyle = (color: string): React.CSSProperties => ({
  width: '42px',
  height: '42px',
  borderRadius: '10px',
  background: `rgba(${parseInt(color.slice(1,3),16) || 99}, ${parseInt(color.slice(3,5),16) || 102}, ${parseInt(color.slice(5,7),16) || 241}, 0.12)`,
  color: color,
  fontSize: '20px',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
});

const summaryLabelStyle: React.CSSProperties = {
  fontSize: '11px',
  color: 'var(--text-muted)',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
};

const summaryValueStyle = (color: string): React.CSSProperties => ({
  fontSize: '24px',
  fontWeight: 800,
  color: color,
  fontFamily: 'var(--font-heading)',
});

const progressCardStyle: React.CSSProperties = {
  padding: '20px 24px',
  marginBottom: '20px',
};

const progressCardHeaderStyle: React.CSSProperties = {
  fontSize: '13px',
  marginBottom: '8px',
};

const pollingIndicatorStyle: React.CSSProperties = {
  fontSize: '11.5px',
  color: 'var(--primary-hover)',
  marginTop: '10px',
  textAlign: 'center',
  fontStyle: 'italic',
};

const actionRowStyle: React.CSSProperties = {
  display: 'flex',
  gap: '12px',
  marginBottom: '16px',
  alignItems: 'center',
};

const confirmBannerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '10px',
  background: 'rgba(239, 68, 68, 0.15)',
  border: '1px solid rgba(239, 68, 68, 0.3)',
  color: '#FCA5A5',
  padding: '12px 16px',
  borderRadius: 'var(--radius-sm)',
  fontSize: '13px',
  marginBottom: '16px',
};

const successBannerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '10px',
  background: 'rgba(16, 185, 129, 0.15)',
  border: '1px solid rgba(16, 185, 129, 0.3)',
  color: '#34D399',
  padding: '12px 16px',
  borderRadius: 'var(--radius-sm)',
  fontSize: '13px',
  marginBottom: '16px',
};

const tableControlsRowStyle: React.CSSProperties = {
  background: 'rgba(14, 18, 46, 0.45)',
  borderBottom: '1px solid var(--border)',
  padding: '14px 24px',
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
};

const tableFooterStyle: React.CSSProperties = {
  background: 'rgba(14, 18, 46, 0.85)',
  borderTop: '1px solid var(--border)',
  padding: '10px 24px',
  fontSize: '11.5px',
  color: 'var(--text-muted)',
  textAlign: 'right',
};
