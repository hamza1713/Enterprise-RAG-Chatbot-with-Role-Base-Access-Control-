import type React from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  Cell,
} from 'recharts';
import {
  Activity,
  AlertTriangle,
  Award,
  CheckCircle,
  ExternalLink,
  FileText,
  Play,
  RefreshCw,
} from 'lucide-react';
import type { EvalStatusResponse, RagasScores } from '../../types';
import { getStatusBadgeStyle } from './evalHelpers';

interface EvalDashboardTabProps {
  evalStatus: EvalStatusResponse | null;
  evalMode: 'full' | 'quality_only' | 'security_only';
  setEvalMode: (mode: 'full' | 'quality_only' | 'security_only') => void;
  useBuiltinDataset: boolean;
  setUseBuiltinDataset: (val: boolean) => void;
  maxPerRole: number;
  setMaxPerRole: (val: number) => void;
  triggerLoading: boolean;
  triggerSuccess: string | null;
  triggerError: string | null;
  isEvalActive: boolean;
  onTriggerEval: (e: React.FormEvent) => void;
  onCancelEval: () => void;
  onOpenHtmlReport: () => void;
}

const CHART_COLORS = ['#509f81', '#8B5CF6', '#3B82F6', '#10B981', '#EC4899'];

function buildScoresData(scores: RagasScores | undefined) {
  if (!scores) return [];
  const labels: Record<string, string> = {
    context_precision: 'Context Precision',
    faithfulness: 'Faithfulness',
    answer_relevancy: 'Answer Relevancy',
    context_recall: 'Context Recall',
    answer_correctness: 'Answer Correctness',
  };
  return Object.entries(scores)
    .filter(([key]) => key in labels)
    .map(([key, val]) => ({
      name: labels[key],
      score: val ? Math.round(val * 100) : 0,
    }));
}

function renderPassFailBadge(pf: 'pass' | 'fail' | 'warn' | undefined) {
  if (!pf) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  if (pf === 'pass') return <span style={{ color: '#34D399', fontWeight: 'bold', fontSize: '11px' }}>PASS</span>;
  if (pf === 'warn') return <span style={{ color: '#FBBF24', fontWeight: 'bold', fontSize: '11px' }}>WARN</span>;
  return <span style={{ color: '#F87171', fontWeight: 'bold', fontSize: '11px' }}>FAIL</span>;
}

export default function EvalDashboardTab({
  evalStatus,
  evalMode,
  setEvalMode,
  useBuiltinDataset,
  setUseBuiltinDataset,
  maxPerRole,
  setMaxPerRole,
  triggerLoading,
  triggerSuccess,
  triggerError,
  isEvalActive,
  onTriggerEval,
  onCancelEval,
  onOpenHtmlReport,
}: EvalDashboardTabProps) {
  const scoresData = buildScoresData(evalStatus?.overall);
  const hasResults = Boolean(evalStatus?.overall && Object.keys(evalStatus.overall).length > 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div className="eval-grid">
        <div className="fs-card" style={{ padding: '24px' }}>
          <div className="eval-card-head">
            <Play size={18} color="var(--primary)" />
            <h2>Run system evaluation</h2>
          </div>
          <p className="eval-card-sub">
            Kick off background metrics evaluations. Runs real RAG pipelines for target roles.
          </p>

          <form onSubmit={onTriggerEval} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {triggerSuccess && (
              <div className="eval-banner-success">
                <CheckCircle size={15} />
                <span>{triggerSuccess}</span>
              </div>
            )}
            {triggerError && (
              <div className="form-error" role="alert">
                {triggerError}
              </div>
            )}

            <div className="eval-input-group">
              <label htmlFor="eval-mode-select">Evaluation Mode</label>
              <select
                id="eval-mode-select"
                className="fs-input"
                value={evalMode}
                onChange={(e) => setEvalMode(e.target.value as 'full' | 'quality_only' | 'security_only')}
                disabled={triggerLoading || isEvalActive}
              >
                <option value="full">Full (Quality + Security)</option>
                <option value="quality_only">Quality Metrics Only</option>
                <option value="security_only">RBAC Security Only</option>
              </select>
            </div>

            <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
              <div className="eval-input-group" style={{ flex: 1 }}>
                <label htmlFor="eval-max-rows">Max rows/role</label>
                <input
                  id="eval-max-rows"
                  type="number"
                  className="fs-input"
                  min={1}
                  max={100}
                  value={maxPerRole}
                  onChange={(e) => setMaxPerRole(Number(e.target.value))}
                  disabled={triggerLoading || isEvalActive || useBuiltinDataset}
                />
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '22px' }}>
                <input
                  type="checkbox"
                  id="builtin-checkbox"
                  checked={useBuiltinDataset}
                  onChange={(e) => setUseBuiltinDataset(e.target.checked)}
                  disabled={triggerLoading || isEvalActive}
                  style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                />
                <label htmlFor="builtin-checkbox" style={{ fontSize: '13px', cursor: 'pointer', color: 'var(--text-secondary)' }}>
                  Use Built-in Testset
                </label>
              </div>
            </div>

            <button
              type="submit"
              className="fs-btn fs-btn-primary"
              disabled={triggerLoading || isEvalActive}
              style={{ height: '44px', width: '100%', marginTop: '6px' }}
            >
              <RefreshCw size={16} className={triggerLoading ? 'spin' : ''} />
              <span>{triggerLoading ? 'Queueing Job...' : 'Launch Evaluation Run'}</span>
            </button>
          </form>
        </div>

        <div className="fs-card" style={{ padding: '24px' }}>
          <div className="eval-card-head">
            <Activity size={18} color="var(--secondary)" />
            <h2>Active job status</h2>
          </div>
          <p className="eval-card-sub">Current benchmark suite pipeline metrics state.</p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div className="eval-status-row">
              <span style={{ color: 'var(--text-secondary)' }}>Job Status:</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {evalStatus?.job_id && (
                  <span style={{ fontSize: '11.5px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }} title={evalStatus.job_id}>
                    #{evalStatus.job_id.slice(0, 8)}
                  </span>
                )}
                <span className="fs-badge" style={getStatusBadgeStyle(evalStatus?.status || 'never_run')}>
                  {evalStatus?.status || 'never_run'}
                </span>
              </div>
            </div>

            {evalStatus?.started_at && (
              <div className="eval-status-row">
                <span style={{ color: 'var(--text-muted)' }}>Started At:</span>
                <span style={{ fontSize: '13px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                  {new Date(evalStatus.started_at).toLocaleString()}
                </span>
              </div>
            )}

            {evalStatus?.completed_at && (
              <div className="eval-status-row">
                <span style={{ color: 'var(--text-muted)' }}>Completed At:</span>
                <span style={{ fontSize: '13px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                  {new Date(evalStatus.completed_at).toLocaleString()}
                </span>
              </div>
            )}

            {isEvalActive && (
              <div className="eval-running-box">
                <span style={{ fontSize: '12px', color: '#FBBF24', fontWeight: '500' }}>
                  {evalStatus?.status === 'queued'
                    ? 'Queued for Taskiq worker…'
                    : 'Executing RAGAS quality benchmarks...'}
                </span>
                {evalStatus?.job_id && (
                  <button
                    type="button"
                    className="fs-btn fs-btn-danger"
                    style={{ height: '30px', padding: '0 12px', fontSize: '12px', marginTop: '4px' }}
                    disabled={triggerLoading}
                    onClick={onCancelEval}
                  >
                    Cancel Run
                  </button>
                )}
              </div>
            )}

            {evalStatus?.status === 'failed' && evalStatus.error && (
              <div className="form-error" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <AlertTriangle size={16} />
                <span>Error: {evalStatus.error}</span>
              </div>
            )}

            {evalStatus?.report_available && (
              <button
                type="button"
                className="fs-btn fs-btn-secondary"
                onClick={onOpenHtmlReport}
                style={{ width: '100%', marginTop: '10px', gap: '8px' }}
              >
                <FileText size={14} />
                <span>Download HTML report</span>
                <ExternalLink size={12} />
              </button>
            )}
          </div>
        </div>
      </div>

      {hasResults && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', width: '100%' }}>
          <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '4px 0' }} />
          {evalStatus?.status !== 'completed' && (
            <div className="eval-warn-banner">
              <AlertTriangle size={14} />
              <span>Displaying results from the last completed run. A new run is in progress or interrupted.</span>
            </div>
          )}
          <div className="eval-results-flex">
            <div className="fs-card" style={{ flex: 1, padding: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <h3 style={{ fontSize: '14.5px', fontWeight: 700, margin: 0 }}>Overall RAGAS Quality Metrics</h3>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Higher is better (0-100%)</span>
              </div>

              {scoresData.length > 0 ? (
                <div style={{ width: '100%', height: '260px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={scoresData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <XAxis dataKey="name" stroke="#64748B" fontSize={11} tickLine={false} />
                      <YAxis domain={[0, 100]} stroke="#64748B" fontSize={11} tickLine={false} />
                      <RechartsTooltip
                        contentStyle={{ background: '#0f171a', border: '1px solid var(--border)', borderRadius: '6px' }}
                        labelStyle={{ color: '#fff', fontWeight: 'bold' }}
                        itemStyle={{ color: 'var(--primary-hover)' }}
                        formatter={(value) => [`${value}%`, 'Score']}
                      />
                      <Bar dataKey="score" radius={[4, 4, 0, 0]} maxBarSize={48}>
                        {scoresData.map((_entry, index) => (
                          <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px', color: 'var(--text-muted)' }}>
                  No quality scores loaded.
                </div>
              )}
            </div>

            <div className="fs-card" style={{ width: '360px', maxWidth: '100%', padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Award size={18} color="var(--primary)" />
                <h3 style={{ fontSize: '14.5px', fontWeight: 700, margin: 0 }}>Metric Threshold Gates</h3>
              </div>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: 0 }}>
                Benchmarked against enterprise-grade RAG quality thresholds.
              </p>

              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '4px' }}>
                <div className="eval-threshold-head">Metric Quality Thresholds</div>
                {evalStatus?.overall &&
                  Object.entries(evalStatus.overall).map(([metric, val], idx) => (
                    <div key={idx} className="eval-threshold-row">
                      <span style={{ fontSize: '12.5px', textTransform: 'capitalize', color: 'var(--text-secondary)' }}>
                        {metric.replace('_', ' ')}
                      </span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <span style={{ fontSize: '13px', fontFamily: 'var(--font-mono)', fontWeight: 'bold' }}>
                          {val ? (val * 100).toFixed(0) : 0}%
                        </span>
                        {renderPassFailBadge(evalStatus.pass_fail?.[metric])}
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
