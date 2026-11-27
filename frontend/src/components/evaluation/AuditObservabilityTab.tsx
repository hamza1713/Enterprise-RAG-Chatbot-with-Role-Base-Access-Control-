import { useCallback, useEffect, useState } from 'react';
import { Download, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { downloadAuditExport, fetchAuditLogs, fetchAuditSummary } from '../../api/audit';
import type { AuditLogRecord, AuditSummary } from '../../types';
import { getStatusBadgeStyle } from './evalHelpers';

export default function AuditObservabilityTab() {
  const [summary, setSummary] = useState<AuditSummary | null>(null);
  const [records, setRecords] = useState<AuditLogRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState('');
  const [eventTypeFilter, setEventTypeFilter] = useState('');
  const [outcomeFilter, setOutcomeFilter] = useState('');
  const [exporting, setExporting] = useState<'csv' | 'ndjson' | null>(null);

  const loadAuditData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sumData, listData] = await Promise.all([
        fetchAuditSummary(30),
        fetchAuditLogs({
          search: search || undefined,
          event_type: eventTypeFilter || undefined,
          outcome: outcomeFilter || undefined,
          limit: 50,
          offset: 0,
        }),
      ]);
      setSummary(sumData);
      setRecords(listData.records || []);
      setTotal(listData.total || 0);
    } catch {
      setError('Failed to load compliance audit trail.');
    } finally {
      setLoading(false);
    }
  }, [search, eventTypeFilter, outcomeFilter]);

  useEffect(() => {
    void loadAuditData();
  }, [loadAuditData]);

  const handleExport = async (format: 'csv' | 'ndjson') => {
    setExporting(format);
    setError(null);
    try {
      await downloadAuditExport(format, {
        search: search || undefined,
        event_type: eventTypeFilter || undefined,
        outcome: outcomeFilter || undefined,
      });
    } catch {
      setError(`Could not export audit logs as ${format.toUpperCase()}.`);
    } finally {
      setExporting(null);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div className="audit-kpi-grid">
        <div className="fs-card audit-kpi-card">
          <span className="audit-kpi-label">30d Total Audit Events</span>
          <strong className="audit-kpi-value">{summary?.total_events ?? 0}</strong>
          <small className="audit-kpi-sub">{summary?.chat_turns ?? 0} AI chat turns</small>
        </div>
        <div className="fs-card audit-kpi-card">
          <span className="audit-kpi-label">Blocked Prompt Injections</span>
          <strong className="audit-kpi-value" style={{ color: '#F87171' }}>
            {summary?.blocked_injections ?? 0}
          </strong>
          <small className="audit-kpi-sub">OWASP LLM01 pre/post checks</small>
        </div>
        <div className="fs-card audit-kpi-card">
          <span className="audit-kpi-label">PII & Secret Redactions</span>
          <strong className="audit-kpi-value" style={{ color: '#FBBF24' }}>
            {summary?.pii_redactions ?? 0}
          </strong>
          <small className="audit-kpi-sub">OWASP LLM02 output filter</small>
        </div>
        <div className="fs-card audit-kpi-card">
          <span className="audit-kpi-label">SQL Retry Rate</span>
          <strong className="audit-kpi-value">
            {((summary?.sql_retry_rate ?? 0) * 100).toFixed(1)}%
          </strong>
          <small className="audit-kpi-sub">
            {summary?.sql_retries ?? 0} retries / {summary?.sql_executions ?? 0} queries
          </small>
        </div>
        <div className="fs-card audit-kpi-card">
          <span className="audit-kpi-label">p95 Latency & Tokens</span>
          <strong className="audit-kpi-value">{summary?.p95_latency_ms ?? 0} ms</strong>
          <small className="audit-kpi-sub">
            {(summary?.total_input_tokens ?? 0) + (summary?.total_output_tokens ?? 0)} total tokens
          </small>
        </div>
      </div>

      <div className="fs-card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '18px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldCheck size={18} color="var(--primary)" />
            <div>
              <h3 style={{ margin: 0, fontSize: '15px' }}>Immutable Compliance Audit Trail (SOC 2 & EU AI Act Art. 50)</h3>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Append-only PostgreSQL log ({total} matching event{total === 1 ? '' : 's'})
              </span>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <button
              type="button"
              className="fs-btn fs-btn-secondary"
              disabled={exporting !== null}
              onClick={() => void handleExport('csv')}
            >
              <Download size={14} />
              <span>{exporting === 'csv' ? 'Exporting CSV…' : 'Export CSV'}</span>
            </button>
            <button
              type="button"
              className="fs-btn fs-btn-secondary"
              disabled={exporting !== null}
              onClick={() => void handleExport('ndjson')}
            >
              <Download size={14} />
              <span>{exporting === 'ndjson' ? 'Exporting NDJSON…' : 'Export NDJSON'}</span>
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={{ position: 'relative', flex: 1, minWidth: '220px' }}>
            <Search size={15} className="eval-search-icon" />
            <input
              type="text"
              className="fs-input"
              style={{ paddingLeft: '38px' }}
              placeholder="Search user, request ID, SQL, or redacted prompt preview..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <select
            aria-label="Filter audit events by type"
            className="fs-input"
            style={{ width: '175px' }}
            value={eventTypeFilter}
            onChange={(e) => setEventTypeFilter(e.target.value)}
          >
            <option value="">All Event Types</option>
            <option value="chat_turn">chat_turn</option>
            <option value="auth_login">auth_login</option>
            <option value="document_upload">document_upload</option>
            <option value="document_role_change">document_role_change</option>
            <option value="document_delete">document_delete</option>
            <option value="rebac_acl_change">rebac_acl_change</option>
            <option value="semantic_model_update">semantic_model_update</option>
          </select>

          <select
            aria-label="Filter audit events by outcome"
            className="fs-input"
            style={{ width: '140px' }}
            value={outcomeFilter}
            onChange={(e) => setOutcomeFilter(e.target.value)}
          >
            <option value="">All Outcomes</option>
            <option value="allow">allow</option>
            <option value="redact">redact</option>
            <option value="block">block</option>
            <option value="cached">cached</option>
            <option value="deny">deny</option>
          </select>

          <button
            type="button"
            className="fs-btn fs-btn-secondary"
            onClick={() => void loadAuditData()}
            disabled={loading}
          >
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
            <span>Refresh</span>
          </button>
        </div>

        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}

        <div className="fs-table-wrap" style={{ marginTop: 0, maxHeight: '460px' }}>
          <table className="fs-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Actor (Role)</th>
                <th>Event</th>
                <th>Mode / Scope</th>
                <th>Outcome</th>
                <th>Guardrails</th>
                <th>Latency / Tokens</th>
                <th>Request ID</th>
              </tr>
            </thead>
            <tbody>
              {records.length === 0 ? (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '28px' }}>
                    {loading ? 'Loading compliance trail…' : 'No audit events match the active filters.'}
                  </td>
                </tr>
              ) : (
                records.map((rec) => (
                  <tr key={rec.event_id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                      {rec.created_at ? new Date(rec.created_at).toLocaleString() : '—'}
                    </td>
                    <td>
                      <strong>{rec.username}</strong>{' '}
                      <span style={{ color: 'var(--text-muted)', fontSize: '11px' }}>
                        ({rec.user_role} · {rec.auth_provider})
                      </span>
                    </td>
                    <td>{rec.event_type}</td>
                    <td>
                      <span>{rec.mode || '—'}</span>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        {rec.authorized_doc_count} docs · {rec.cited_doc_ids.length} cited
                      </div>
                    </td>
                    <td>
                      <span className="fs-badge" style={getStatusBadgeStyle(rec.outcome)}>
                        {rec.outcome}
                      </span>
                    </td>
                    <td style={{ fontSize: '11px', color: rec.guardrail_flags.length ? '#FBBF24' : 'var(--text-muted)' }}>
                      {rec.guardrail_flags.length ? rec.guardrail_flags.join(', ') : 'none'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                      {rec.latency_ms} ms
                      {(rec.input_tokens || rec.output_tokens) ? (
                        <div style={{ color: 'var(--text-muted)' }}>
                          {(rec.input_tokens || 0) + (rec.output_tokens || 0)} tok
                        </div>
                      ) : null}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }} title={rec.request_id}>
                      {rec.request_id.slice(0, 12)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
