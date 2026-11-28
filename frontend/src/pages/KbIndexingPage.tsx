import React, { useState, useEffect, useCallback } from 'react';
import client from '../api/client';
import { deleteDocument, reindexDocument } from '../api/documents';
import { cancelJob, fetchJobs, retryJob } from '../api/jobs';
import type { BulkStatusResponse, DocIndexingDetail, JobRecord } from '../types';
import {
  CheckCircle,
  RefreshCw,
  AlertTriangle,
  RotateCcw,
  Search,
  Trash2,
  XCircle,
  ListChecks,
} from 'lucide-react';

export default function KbIndexingPage() {
  const [bulkData, setBulkData] = useState<BulkStatusResponse | null>(null);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [confirmReindex, setConfirmReindex] = useState(false);
  const [confirmDeleteDocId, setConfirmDeleteDocId] = useState<number | null>(null);
  const [confirmMsg, setConfirmMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState('All');
  const [searchTerm, setSearchTerm] = useState('');

  const fetchStatus = useCallback(async (showLoader = true) => {
    if (showLoader) setLoading(true);
    try {
      const [statusRes, jobsList] = await Promise.all([
        client.get('/indexing-status-bulk'),
        fetchJobs({ job_type: 'index', limit: 20 }),
      ]);
      setBulkData(statusRes.data);
      setJobs(jobsList);
    } catch (e) {
      console.error('Failed to fetch bulk indexing status or jobs', e);
    } finally {
      if (showLoader) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    const hasPendingDocs = Boolean(bulkData?.summary && bulkData.summary.pending > 0);
    const hasActiveJobs = jobs.some((j) =>
      ['queued', 'running', 'cancel_requested'].includes(j.status),
    );
    if (!hasPendingDocs && !hasActiveJobs) return;

    const interval = setInterval(() => {
      void fetchStatus(false);
    }, 4000);

    return () => clearInterval(interval);
  }, [bulkData, jobs, fetchStatus]);

  const handleRetry = async () => {
    setActionLoading(true);
    setSuccessMsg(null);
    setConfirmMsg(null);
    try {
      const res = await client.post('/reindex-retry');
      setSuccessMsg(res.data.message || 'Retry queued successfully.');
      void fetchStatus(false);
    } catch (e: any) {
      setConfirmMsg(e.response?.data?.detail || 'Retry failed. Check backend logs.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleReindex = async () => {
    if (!confirmReindex) {
      setConfirmReindex(true);
      setConfirmMsg(
        '⚠️ Confirm full re-index — active documents remain searchable while chunks are refreshed in the background. Click again to confirm.',
      );
      return;
    }

    setActionLoading(true);
    setSuccessMsg(null);
    setConfirmMsg(null);
    setConfirmReindex(false);
    try {
      const res = await client.post('/reindex');
      setSuccessMsg(res.data.message || 'Full re-index queued successfully.');
      void fetchStatus(false);
    } catch (e: any) {
      setConfirmMsg(e.response?.data?.detail || 'Failed to start re-index. Check logs.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleDocReindex = async (doc: DocIndexingDetail) => {
    setActionLoading(true);
    setSuccessMsg(null);
    setConfirmMsg(null);
    try {
      const res = await reindexDocument(doc.id);
      setSuccessMsg(res.message || `Queued reindex for '${doc.filename}'.`);
      void fetchStatus(false);
    } catch (e: any) {
      setConfirmMsg(e.response?.data?.detail || `Failed to queue reindex for '${doc.filename}'.`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleDocDelete = async (doc: DocIndexingDetail) => {
    if (confirmDeleteDocId !== doc.id) {
      setConfirmDeleteDocId(doc.id);
      setConfirmMsg(`Click Delete again on '${doc.filename}' to permanently remove the document, chunks, and datasets.`);
      return;
    }
    setConfirmDeleteDocId(null);
    setConfirmMsg(null);
    setSuccessMsg(null);
    setActionLoading(true);
    try {
      const res = await deleteDocument(doc.id);
      setSuccessMsg(res.message || `Deleted '${doc.filename}'.`);
      void fetchStatus(false);
    } catch (e: any) {
      setConfirmMsg(e.response?.data?.detail || `Failed to delete '${doc.filename}'.`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleCancelJob = async (jobId: string) => {
    setActionLoading(true);
    setSuccessMsg(null);
    setConfirmMsg(null);
    try {
      await cancelJob(jobId);
      setSuccessMsg(`Cancellation sent for job ${jobId.slice(0, 8)}…`);
      void fetchStatus(false);
    } catch (e: any) {
      setConfirmMsg(e.response?.data?.detail || 'Could not cancel job.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleRetryJob = async (jobId: string) => {
    setActionLoading(true);
    setSuccessMsg(null);
    setConfirmMsg(null);
    try {
      const created = await retryJob(jobId);
      setSuccessMsg(`Re-queued durable job ${created.id.slice(0, 8)}…`);
      void fetchStatus(false);
    } catch (e: any) {
      setConfirmMsg(e.response?.data?.detail || 'Could not retry job.');
    } finally {
      setActionLoading(false);
    }
  };

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

  const getJobBadge = (status: string) => {
    if (status === 'completed') return <span className="fs-badge fs-badge-success">Completed</span>;
    if (status === 'running' || status === 'queued') return <span className="fs-badge fs-badge-warning">{status}</span>;
    if (status === 'cancel_requested' || status === 'cancelled') return <span className="fs-badge">{status}</span>;
    return <span className="fs-badge fs-badge-danger">{status}</span>;
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

  const filteredDocs = allDocs.filter((doc) => {
    const matchesStatus =
      statusFilter === 'All' ||
      (statusFilter === '✅ Indexed' && doc.status === 'indexed') ||
      (statusFilter === '⏳ Pending' && doc.status === 'pending') ||
      (statusFilter === '❌ Failed' && doc.status === 'failed');

    const matchesSearch =
      !searchTerm || doc.filename.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesStatus && matchesSearch;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', paddingBottom: '32px' }}>
      <div className="fs-header">
        <h1 className="fs-title">Knowledge base</h1>
        <p className="fs-subtitle">
          Monitor Taskiq indexing jobs, Docling PDF parsing, contextual retrieval chunks, and per-document operations.
        </p>
      </div>

      {/* Summary Cards */}
      <div style={summaryGridStyle}>
        <div style={summaryCardStyle('#9bd8bd')}>
          <div style={summaryIconStyle('#9bd8bd')}>📁</div>
          <div>
            <div style={summaryLabelStyle}>Total Docs</div>
            <div style={summaryValueStyle('#9bd8bd')}>{summary.total}</div>
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
              background:
                summary.pending > 0
                  ? 'linear-gradient(90deg, var(--primary), var(--secondary))'
                  : summary.failed > 0 && summary.pending === 0
                    ? '#EF4444'
                    : '#10B981',
            }}
          />
        </div>
      </div>

      {/* Action Buttons panel */}
      <div style={actionRowStyle}>
        <button
          className="fs-btn fs-btn-secondary"
          onClick={handleRetry}
          disabled={actionLoading}
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
          <span>Re-index All (Non-Destructive)</span>
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

      {/* Background Jobs Queue */}
      <div className="fs-card" style={{ display: 'flex', flexDirection: 'column', padding: 0, overflow: 'hidden' }}>
        <div style={tableControlsRowStyle}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ListChecks size={16} color="var(--primary)" />
            <h3 style={{ fontSize: '14px', fontWeight: 700, margin: 0 }}>Background Jobs Queue</h3>
          </div>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Showing latest {jobs.length} indexing jobs
          </span>
        </div>

        <div className="fs-table-wrap" style={{ border: 'none', borderRadius: 0, margin: 0, maxHeight: '260px', overflowY: 'auto' }}>
          <table className="fs-table">
            <thead>
              <tr>
                <th>Job ID</th>
                <th>Type</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Attempts</th>
                <th style={{ textAlign: 'right' }}>Controls</th>
              </tr>
            </thead>
            <tbody>
              {jobs.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>
                    No indexing jobs recorded yet.
                  </td>
                </tr>
              ) : (
                jobs.map((job) => {
                  const pctJob =
                    job.progress_total > 0
                      ? Math.min(100, Math.round((job.progress_current / job.progress_total) * 100))
                      : job.status === 'completed'
                        ? 100
                        : 0;
                  const canCancel = job.status === 'queued' || job.status === 'running';
                  const canRetry = job.status === 'failed' || job.status === 'cancelled';
                  return (
                    <tr key={job.id}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }} title={job.id}>
                        {job.id.slice(0, 8)}
                      </td>
                      <td style={{ fontSize: '12.5px' }}>{job.job_type}</td>
                      <td>{getJobBadge(job.status)}</td>
                      <td style={{ minWidth: '180px' }}>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '3px' }}>
                          {job.error ? (
                            <span style={{ color: '#FCA5A5' }} title={job.error}>
                              {job.error.slice(0, 60)}
                            </span>
                          ) : (
                            job.progress_message || `${pctJob}%`
                          )}
                        </div>
                        <div className="progress-bar-track">
                          <div
                            className="progress-bar-fill"
                            style={{
                              width: `${pctJob}%`,
                              background: job.status === 'failed' ? '#EF4444' : '#10B981',
                            }}
                          />
                        </div>
                      </td>
                      <td style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                        {job.attempts}/{job.max_attempts}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', gap: '6px' }}>
                          {canCancel && (
                            <button
                              type="button"
                              className="fs-btn fs-btn-danger"
                              style={{ height: '28px', padding: '0 8px', fontSize: '11.5px' }}
                              disabled={actionLoading}
                              onClick={() => handleCancelJob(job.id)}
                            >
                              <XCircle size={12} />
                              <span>Cancel</span>
                            </button>
                          )}
                          {canRetry && (
                            <button
                              type="button"
                              className="fs-btn fs-btn-secondary"
                              style={{ height: '28px', padding: '0 8px', fontSize: '11.5px' }}
                              disabled={actionLoading}
                              onClick={() => handleRetryJob(job.id)}
                            >
                              <RotateCcw size={12} />
                              <span>Retry</span>
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Per Document Table */}
      <div className="fs-card" style={{ display: 'flex', flexDirection: 'column', padding: 0, overflow: 'hidden' }}>
        <div style={tableControlsRowStyle}>
          <h3 style={{ fontSize: '14px', fontWeight: 700, margin: 0 }}>📋 Document Indexing Details</h3>

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
              <Search
                size={13}
                style={{
                  position: 'absolute',
                  left: '10px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  color: 'var(--text-muted)',
                }}
              />
            </div>
          </div>
        </div>

        <div className="fs-table-wrap" style={{ border: 'none', borderRadius: 0, margin: 0, maxHeight: '420px', overflowY: 'auto' }}>
          <table className="fs-table">
            <thead>
              <tr>
                <th style={{ width: '50px', minWidth: '50px', textAlign: 'center', background: '#233331', color: 'var(--primary-hover)', fontWeight: 'bold', position: 'sticky', left: 0, zIndex: 12 }}>
                  #
                </th>
                <th>Document</th>
                <th>Role</th>
                <th>Parser</th>
                <th>Status</th>
                <th>Chunk Progress</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredDocs.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                    {allDocs.length === 0 ? 'No documents ingested yet.' : 'No records match filter parameters.'}
                  </td>
                </tr>
              ) : (
                filteredDocs.map((doc, idx) => {
                  const prog = doc.total_chunks > 0 ? `${doc.embedded_chunks}/${doc.total_chunks}` : '—';
                  const rowPct =
                    doc.total_chunks > 0
                      ? Math.floor((doc.embedded_chunks / doc.total_chunks) * 100)
                      : 0;
                  return (
                    <tr key={doc.id || idx}>
                      <td style={{ textAlign: 'center', background: 'rgba(94,157,128, 0.05)', fontWeight: 'bold', color: 'var(--text-muted)', position: 'sticky', left: 0, zIndex: 5, borderRight: '1px solid rgba(94,157,128, 0.15)' }}>
                        {idx + 1}
                      </td>
                      <td
                        style={{ color: '#E2E8F0', maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={doc.filename}
                      >
                        {doc.filename}
                      </td>
                      <td>
                        <span style={{ color: getRoleColor(doc.role), fontWeight: 700 }}>{doc.role}</span>
                      </td>
                      <td style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                        {doc.parser_used || '—'}
                      </td>
                      <td title={doc.last_error || undefined}>{getStatusBadge(doc.status)}</td>
                      <td style={{ minWidth: '140px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10.5px', color: 'var(--text-muted)', marginBottom: '3px' }}>
                          <span>{prog} chunks</span>
                          <span>{rowPct}%</span>
                        </div>
                        <div className="progress-bar-track">
                          <div
                            className="progress-bar-fill"
                            style={{
                              width: `${rowPct}%`,
                              background: getProgressBarColor(doc.status),
                            }}
                          />
                        </div>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', gap: '6px' }}>
                          <button
                            type="button"
                            className="fs-btn fs-btn-secondary"
                            style={{ height: '28px', padding: '0 8px', fontSize: '11.5px' }}
                            disabled={actionLoading}
                            onClick={() => handleDocReindex(doc)}
                          >
                            <RotateCcw size={12} />
                            <span>Reindex</span>
                          </button>
                          <button
                            type="button"
                            className="fs-btn fs-btn-danger"
                            style={{ height: '28px', padding: '0 8px', fontSize: '11.5px' }}
                            disabled={actionLoading}
                            onClick={() => handleDocDelete(doc)}
                          >
                            <Trash2 size={12} />
                            <span>{confirmDeleteDocId === doc.id ? 'Confirm?' : 'Delete'}</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <div style={tableFooterStyle}>
          Showing {filteredDocs.length} of {allDocs.length} documents
        </div>
      </div>
    </div>
  );
}

const summaryGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 180px), 1fr))',
  gap: '16px',
  marginBottom: '4px',
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
  background: `rgba(${parseInt(color.slice(1, 3), 16) || 99}, ${parseInt(color.slice(3, 5), 16) || 102}, ${parseInt(color.slice(5, 7), 16) || 241}, 0.12)`,
  color,
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
  color,
  fontFamily: 'var(--font-heading)',
});

const progressCardStyle: React.CSSProperties = {
  padding: '20px 24px',
};

const progressCardHeaderStyle: React.CSSProperties = {
  fontSize: '13px',
  marginBottom: '8px',
};

const actionRowStyle: React.CSSProperties = {
  display: 'flex',
  gap: '12px',
  flexWrap: 'wrap',
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
};

const tableControlsRowStyle: React.CSSProperties = {
  background: 'rgba(22,34,37, 0.45)',
  borderBottom: '1px solid var(--border)',
  padding: '14px 24px',
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  flexWrap: 'wrap',
  gap: '10px',
};

const tableFooterStyle: React.CSSProperties = {
  background: 'rgba(22,34,37, 0.85)',
  borderTop: '1px solid var(--border)',
  padding: '10px 24px',
  fontSize: '11.5px',
  color: 'var(--text-muted)',
  textAlign: 'right',
};
