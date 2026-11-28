import { useState } from 'react';
import {
  Activity,
  ArrowUpDown,
  Award,
  FileText,
  Filter,
  Maximize2,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';
import type { RagasEvalRecord } from '../../types';
import { parseContexts } from '../../utils/parseContexts';
import {
  METRIC_KEYS,
  ROLE_COLORS,
  checkMetricStatus,
  getMetricColor,
  getOverallRecordStatus,
} from './evalHelpers';

interface EvalRecordsTabProps {
  records: RagasEvalRecord[];
  recordsLoading: boolean;
  onRefresh: () => void;
}

export default function EvalRecordsTab({ records, recordsLoading, onRefresh }: EvalRecordsTabProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'pass' | 'warn' | 'fail'>('all');
  const [sortConfig, setSortConfig] = useState<{ key: string; direction: 'asc' | 'desc' } | null>(null);
  const [selectedRecord, setSelectedRecord] = useState<RagasEvalRecord | null>(null);

  const handleSort = (key: string) => {
    let direction: 'asc' | 'desc' = 'asc';
    if (sortConfig && sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setSortConfig({ key, direction });
  };

  const filtered = records.filter((r) => {
    const matchesSearch =
      r.user_input.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.response.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.reference.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesRole = roleFilter === 'all' || r.role.toLowerCase() === roleFilter.toLowerCase();
    const matchesStatus = statusFilter === 'all' || getOverallRecordStatus(r) === statusFilter;
    return matchesSearch && matchesRole && matchesStatus;
  });

  const sorted = sortConfig
    ? [...filtered].sort((a, b) => {
        const aVal = a[sortConfig.key as keyof RagasEvalRecord];
        const bVal = b[sortConfig.key as keyof RagasEvalRecord];
        if (aVal === undefined || aVal === null) return 1;
        if (bVal === undefined || bVal === null) return -1;
        if (typeof aVal === 'string' && typeof bVal === 'string') {
          return sortConfig.direction === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
        }
        return sortConfig.direction === 'asc' ? Number(aVal) - Number(bVal) : Number(bVal) - Number(aVal);
      })
    : filtered;

  return (
    <>
      <div className="fs-card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', flex: 1, minWidth: '240px' }}>
            <Search size={16} className="eval-search-icon" />
            <input
              type="text"
              placeholder="Search questions, references, or responses..."
              className="fs-input"
              style={{ paddingLeft: '40px' }}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <Filter size={14} color="var(--text-muted)" />
            <select
              aria-label="Filter test cases by role"
              className="fs-input"
              style={{ width: '130px', padding: '8px 12px', height: '38px' }}
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
            >
              <option value="all">All Roles</option>
              {Array.from(new Set(records.map((r) => r.role))).map((role) => (
                <option key={role} value={role}>
                  {role.toUpperCase()}
                </option>
              ))}
            </select>
          </div>

          <select
            aria-label="Filter test cases by status"
            className="fs-input"
            style={{ width: '130px', padding: '8px 12px', height: '38px' }}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as 'all' | 'pass' | 'warn' | 'fail')}
          >
            <option value="all">All Statuses</option>
            <option value="pass">PASS Only</option>
            <option value="warn">WARN Only</option>
            <option value="fail">FAIL Only</option>
          </select>

          <button
            type="button"
            className="fs-btn fs-btn-secondary"
            style={{ height: '38px', padding: '0 16px' }}
            onClick={onRefresh}
            disabled={recordsLoading}
          >
            <RefreshCw size={14} className={recordsLoading ? 'spin' : ''} />
            <span>Refresh</span>
          </button>
        </div>

        {recordsLoading ? (
          <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
            Loading evaluation test runs...
          </div>
        ) : sorted.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
            No evaluation records found matching your filters.
          </div>
        ) : (
          <div className="fs-table-wrap" style={{ marginTop: 0, maxHeight: '450px' }}>
            <table className="fs-table">
              <thead>
                <tr>
                  <th onClick={() => handleSort('user_input')} className="eval-sortable-th">
                    <span>Question</span>
                    <ArrowUpDown size={12} style={{ opacity: 0.7 }} />
                  </th>
                  <th onClick={() => handleSort('role')} className="eval-sortable-th">
                    <span>Role</span>
                    <ArrowUpDown size={12} style={{ opacity: 0.7 }} />
                  </th>
                  {METRIC_KEYS.map((m) => (
                    <th key={m} onClick={() => handleSort(m)} className="eval-sortable-th">
                      <span>{m.replace('answer_', '').replace('context_', '')}</span>
                      <ArrowUpDown size={12} style={{ opacity: 0.7 }} />
                    </th>
                  ))}
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((record, index) => {
                  const borderColor = ROLE_COLORS[record.role.toLowerCase()] || '#64748B';
                  return (
                    <tr key={index}>
                      <td
                        style={{
                          maxWidth: '280px',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          borderLeft: `3px solid ${borderColor}`,
                          paddingLeft: '12px',
                        }}
                        title={record.user_input}
                      >
                        {record.user_input}
                      </td>
                      <td>
                        <span className="eval-role-pill" style={{ color: borderColor, borderColor: `${borderColor}40` }}>
                          {record.role.toUpperCase()}
                        </span>
                      </td>
                      {METRIC_KEYS.map((met) => {
                        const val = record[met as keyof RagasEvalRecord] as number | undefined;
                        if (val === undefined || val === null) {
                          return (
                            <td key={met} style={{ color: 'var(--text-muted)', textAlign: 'center' }}>
                              —
                            </td>
                          );
                        }
                        const status = checkMetricStatus(met, val);
                        return (
                          <td key={met} style={{ color: getMetricColor(status), fontFamily: 'var(--font-mono)' }}>
                            {val.toFixed(2)}
                          </td>
                        );
                      })}
                      <td>
                        <button
                          type="button"
                          className="fs-btn fs-btn-secondary"
                          style={{ padding: '4px 8px', fontSize: '11px', height: '26px' }}
                          onClick={() => setSelectedRecord(record)}
                        >
                          <Maximize2 size={11} />
                          <span>View</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selectedRecord && (
        <div className="fs-overlay">
          <div className="fs-card fs-modal" style={{ maxWidth: '880px', padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ margin: 0 }}>Test Case Details — {selectedRecord.role.toUpperCase()}</h3>
              <button
                type="button"
                className="icon-button"
                aria-label="Close detail modal"
                onClick={() => setSelectedRecord(null)}
              >
                <X size={18} />
              </button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div className="eval-glossary-item">
                <strong style={{ fontSize: '11px', color: 'var(--text-muted)' }}>QUESTION</strong>
                <div style={{ fontSize: '14px', marginTop: '4px' }}>{selectedRecord.user_input}</div>
              </div>
              <div className="eval-grid">
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                    <Award size={14} color="#10B981" />
                    <strong style={{ fontSize: '12px' }}>Reference Answer</strong>
                  </div>
                  <div className="eval-text-box">{selectedRecord.reference}</div>
                </div>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                    <Activity size={14} color="#509f81" />
                    <strong style={{ fontSize: '12px' }}>Generated RAG Response</strong>
                  </div>
                  <div className="eval-text-box">{selectedRecord.response}</div>
                </div>
              </div>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                  <FileText size={14} color="#8B5CF6" />
                  <strong style={{ fontSize: '12px' }}>Retrieved Context Chunks</strong>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '180px', overflowY: 'auto' }}>
                  {parseContexts(selectedRecord.retrieved_contexts).map((chunk, idx) => (
                    <div key={idx} className="eval-glossary-item">
                      <strong style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Chunk #{idx + 1}</strong>
                      <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>{chunk}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
