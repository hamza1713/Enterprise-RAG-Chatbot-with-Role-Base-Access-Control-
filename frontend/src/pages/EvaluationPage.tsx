import React, { useState, useEffect } from 'react';
import client, { API_URL } from '../api/client';
import { useAuthStore } from '../store/authStore';
import type { RagasScores, EvalStatusResponse } from '../types';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
} from 'recharts';
import {
  Activity,
  Play,
  FileText,
  ShieldCheck,
  ShieldAlert,
  ExternalLink,
  CheckCircle,
  AlertTriangle,
} from 'lucide-react';

export default function EvaluationPage() {
  const { token } = useAuthStore();
  const [evalStatus, setEvalStatus] = useState<EvalStatusResponse | null>(null);
  const [, setLoading] = useState(false);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [triggerSuccess, setTriggerSuccess] = useState<string | null>(null);

  // Trigger form state
  const [evalMode, setEvalMode] = useState<'full' | 'quality_only' | 'security_only'>('full');
  const [useBuiltinDataset, setUseBuiltinDataset] = useState(false);
  const [maxPerRole, setMaxPerRole] = useState(15);

  const fetchStatus = async (showLoader = true) => {
    if (showLoader) setLoading(true);
    try {
      const res = await client.get('/evaluate/status');
      setEvalStatus(res.data);
    } catch (e) {
      console.error('Failed to fetch evaluation status', e);
    } finally {
      if (showLoader) setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  // Poll status while evaluation is running
  useEffect(() => {
    if (evalStatus?.status !== 'running') return;

    const interval = setInterval(() => {
      fetchStatus(false);
    }, 4000);

    return () => clearInterval(interval);
  }, [evalStatus]);

  const handleTriggerEval = async (e: React.FormEvent) => {
    e.preventDefault();
    setTriggerLoading(true);
    setTriggerSuccess(null);

    try {
      const res = await client.post('/evaluate', {
        mode: evalMode,
        max_per_role: maxPerRole,
        use_builtin_dataset: useBuiltinDataset
      });
      setTriggerSuccess(res.data.message || 'Evaluation started in background.');
      fetchStatus(false);
      setTimeout(() => {
        setTriggerSuccess(null);
      }, 3000);
    } catch (e: any) {
      console.error('Failed to trigger RAGAS evaluation', e);
      alert(e.response?.data?.detail || 'Failed to start evaluation.');
    } finally {
      setTriggerLoading(false);
    }
  };

  const handleOpenHtmlReport = () => {
    if (!token) return;
    const url = `${API_URL}/evaluate/report?token=${token}`;
    window.open(url, '_blank');
  };

  // Convert scores object to Recharts compatible array
  const getChartData = (scores: RagasScores | undefined) => {
    if (!scores) return [];
    
    // RAGAS metric labels mapper
    const labels: Record<string, string> = {
      context_precision: 'Context Precision',
      faithfulness: 'Faithfulness',
      answer_relevancy: 'Answer Relevancy',
      context_recall: 'Context Recall',
    };

    return Object.entries(scores)
      .filter(([key]) => key in labels)
      .map(([key, val]) => ({
        name: labels[key],
        score: val ? Math.round(val * 100) : 0,
      }));
  };

  const scoresData = getChartData(evalStatus?.overall);
  const COLORS = ['#6366F1', '#8B5CF6', '#10B981', '#06B6D4'];

  const getStatusBadgeStyle = (status: string) => {
    const clean = status.toLowerCase();
    if (clean === 'completed' || clean === 'passed' || clean === 'safe') {
      return { background: 'rgba(16, 185, 129, 0.12)', color: '#34D399', border: '1px solid rgba(16, 185, 129, 0.25)' };
    }
    if (clean === 'running') {
      return { background: 'rgba(245, 158, 11, 0.12)', color: '#FBBF24', border: '1px solid rgba(245, 158, 11, 0.25)' };
    }
    if (clean === 'failed') {
      return { background: 'rgba(239, 68, 68, 0.12)', color: '#F87171', border: '1px solid rgba(239, 68, 68, 0.25)' };
    }
    return { background: 'rgba(255, 255, 255, 0.05)', color: 'var(--text-muted)', border: '1px solid rgba(255,255,255,0.08)' };
  };

  const getPassFailBadge = (pf: 'pass' | 'fail' | undefined) => {
    if (!pf) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
    return pf === 'pass' ? (
      <span style={{ color: '#34D399', fontWeight: 'bold' }}>PASS</span>
    ) : (
      <span style={{ color: '#F87171', fontWeight: 'bold' }}>FAIL</span>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header */}
      <div className="fs-header">
        <h1 className="fs-title">📈 Evaluation Dashboard</h1>
        <p className="fs-subtitle">Trigger quality benchmarks (RAGAS) and access-control security suite test runs.</p>
      </div>

      <div style={gridStyle}>
        {/* Trigger card */}
        <div className="fs-card" style={cardStyle}>
          <div style={cardTitleContainerStyle}>
            <Play size={18} color="var(--primary)" />
            <h2 style={cardTitleStyle}>Run system evaluation</h2>
          </div>
          <p style={cardSubtitleStyle}>Kick off background metrics evaluations. Requires LLM generation runs.</p>

          <form onSubmit={handleTriggerEval} style={formStyle}>
            {triggerSuccess && (
              <div style={successBannerStyle}>
                <CheckCircle size={15} />
                <span>{triggerSuccess}</span>
              </div>
            )}

            <div style={inputGroupStyle}>
              <label style={labelStyle}>Evaluation Mode</label>
              <select
                className="fs-input"
                value={evalMode}
                onChange={(e) => setEvalMode(e.target.value as any)}
                disabled={triggerLoading || evalStatus?.status === 'running'}
              >
                <option value="full">Full (Quality + Security)</option>
                <option value="quality_only">Quality Metrics Only</option>
                <option value="security_only">RBAC Security Only</option>
              </select>
            </div>

            <div style={{ display: 'flex', gap: '16px' }}>
              <div style={{ ...inputGroupStyle, flex: 1 }}>
                <label style={labelStyle}>Max rows/role</label>
                <input
                  type="number"
                  className="fs-input"
                  min={1}
                  max={100}
                  value={maxPerRole}
                  onChange={(e) => setMaxPerRole(Number(e.target.value))}
                  disabled={triggerLoading || evalStatus?.status === 'running' || useBuiltinDataset}
                />
              </div>

              <div style={checkboxGroupStyle}>
                <input
                  type="checkbox"
                  id="builtin-checkbox"
                  checked={useBuiltinDataset}
                  onChange={(e) => setUseBuiltinDataset(e.target.checked)}
                  disabled={triggerLoading || evalStatus?.status === 'running'}
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
              disabled={triggerLoading || evalStatus?.status === 'running'}
              style={{ height: '44px', width: '100%', marginTop: '10px' }}
            >
              <span>{triggerLoading ? 'Queueing Job...' : 'Launch Evaluation Run'}</span>
            </button>
          </form>
        </div>

        {/* Status card */}
        <div className="fs-card" style={cardStyle}>
          <div style={cardTitleContainerStyle}>
            <Activity size={18} color="var(--secondary)" />
            <h2 style={cardTitleStyle}>Active job status</h2>
          </div>
          <p style={cardSubtitleStyle}>Current benchmark suite pipeline metrics state.</p>

          <div style={statusInnerContainerStyle}>
            <div style={statusRowStyle}>
              <span style={{ color: 'var(--text-secondary)' }}>Job Status:</span>
              <span 
                className="fs-badge" 
                style={getStatusBadgeStyle(evalStatus?.status || 'never_run')}
              >
                {evalStatus?.status || 'never_run'}
              </span>
            </div>

            {evalStatus?.started_at && (
              <div style={statusRowStyle}>
                <span style={{ color: 'var(--text-muted)' }}>Started At:</span>
                <span style={{ fontSize: '13px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                  {new Date(evalStatus.started_at).toLocaleString()}
                </span>
              </div>
            )}

            {evalStatus?.completed_at && (
              <div style={statusRowStyle}>
                <span style={{ color: 'var(--text-muted)' }}>Completed At:</span>
                <span style={{ fontSize: '13px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                  {new Date(evalStatus.completed_at).toLocaleString()}
                </span>
              </div>
            )}

            {evalStatus?.status === 'running' && (
              <div style={runningGlowContainerStyle}>
                <div className="chat-thinking" style={{ width: '100%', justifyContent: 'center' }}>
                  <span></span>
                  <span></span>
                  <span></span>
                  <span style={{ marginLeft: '6px' }}>Executing RAGAS quality benchmarks...</span>
                </div>
              </div>
            )}

            {evalStatus?.status === 'failed' && evalStatus.error && (
              <div style={failAlertBoxStyle}>
                <AlertTriangle size={16} />
                <span>Error: {evalStatus.error}</span>
              </div>
            )}

            {evalStatus?.report_available && (
              <button 
                className="fs-btn fs-btn-secondary" 
                onClick={handleOpenHtmlReport}
                style={{ width: '100%', marginTop: '16px', gap: '8px' }}
              >
                <FileText size={14} />
                <span>Open Detailed HTML Report</span>
                <ExternalLink size={12} />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Results Section */}
      {evalStatus?.status === 'completed' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '10px 0' }} />
          
          <div style={resultsGridStyle}>
            {/* Recharts Bar chart */}
            <div className="fs-card" style={{ flex: 1, padding: '24px' }}>
              <h3 style={{ fontSize: '14.5px', fontWeight: 700, marginBottom: '20px' }}>📊 RAGAS Performance Quality Indices</h3>
              
              {scoresData.length > 0 ? (
                <div style={{ width: '100%', height: '240px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={scoresData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <XAxis dataKey="name" stroke="#64748B" fontSize={11} tickLine={false} />
                      <YAxis domain={[0, 100]} stroke="#64748B" fontSize={11} tickLine={false} />
                      <Tooltip 
                        contentStyle={{ background: '#0a0d24', border: '1px solid var(--border)', borderRadius: '6px' }}
                        labelStyle={{ color: '#fff', fontWeight: 'bold' }}
                        itemStyle={{ color: 'var(--primary-hover)' }}
                      />
                      <Bar dataKey="score" radius={[4, 4, 0, 0]} maxBarSize={48}>
                        {scoresData.map((_entry, index) => (
                          <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div style={emptyScoresStyle}>No quality scores loaded.</div>
              )}
            </div>

            {/* Pass/Fail & Security overall card */}
            <div className="fs-card" style={{ width: '380px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <h3 style={{ fontSize: '14.5px', fontWeight: 700 }}>🛡️ Access-Control Verification</h3>

              {/* RBAC overall badge */}
              <div style={rbacRowContainerStyle}>
                {evalStatus.rbac_overall === 'Passed' ? (
                  <div style={rbacPassBoxStyle}>
                    <ShieldCheck size={28} color="#34D399" />
                    <div>
                      <div style={{ fontWeight: 'bold', fontSize: '14px', color: '#fff' }}>RBAC Strict Policy Verified</div>
                      <div style={{ fontSize: '11px', color: '#94A3B8', marginTop: '2px' }}>Zero cross-department leakage events.</div>
                    </div>
                  </div>
                ) : (
                  <div style={rbacFailBoxStyle}>
                    <ShieldAlert size={28} color="#F87171" />
                    <div>
                      <div style={{ fontWeight: 'bold', fontSize: '14px', color: '#fff' }}>RBAC Leaks Detected!</div>
                      <div style={{ fontSize: '11px', color: '#FCA5A5', marginTop: '2px' }}>Unauthorized queries bypass filters.</div>
                    </div>
                  </div>
                )}
              </div>

              {/* RAGAS Individual thresholds */}
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '4px' }}>
                <div style={thresholdHeaderStyle}>Metric Quality Thresholds</div>
                
                {evalStatus.overall && Object.entries(evalStatus.overall).map(([metric, val], idx) => {
                  const passState = evalStatus.pass_fail?.[metric];
                  const label = metric.replace('_', ' ');
                  return (
                    <div key={idx} style={thresholdRowStyle}>
                      <span style={{ fontSize: '12.5px', textTransform: 'capitalize', color: 'var(--text-secondary)' }}>
                        {label}
                      </span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <span style={{ fontSize: '13px', fontFamily: 'var(--font-mono)', fontWeight: 'bold' }}>
                          {val ? (val * 100).toFixed(0) : 0}%
                        </span>
                        {getPassFailBadge(passState)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Inline CSS Styles for Evaluation
const gridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr',
  gap: '24px',
};

const cardStyle: React.CSSProperties = {
  padding: '24px',
};

const cardTitleContainerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '12px',
  marginBottom: '6px',
};

const cardTitleStyle: React.CSSProperties = {
  fontSize: '16px',
  fontWeight: 700,
  color: '#ffffff',
  margin: 0,
};

const cardSubtitleStyle: React.CSSProperties = {
  fontSize: '12px',
  color: 'var(--text-muted)',
  marginBottom: '20px',
};

const formStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '16px',
};

const inputGroupStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '6px',
};

const labelStyle: React.CSSProperties = {
  fontSize: '11px',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  color: 'var(--text-secondary)',
};

const checkboxGroupStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
  marginTop: '22px',
};

const statusInnerContainerStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '14px',
};

const statusRowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  fontSize: '13.5px',
};

const runningGlowContainerStyle: React.CSSProperties = {
  marginTop: '8px',
  padding: '10px',
  borderRadius: '8px',
  border: '1px dashed rgba(245, 158, 11, 0.25)',
  background: 'rgba(245, 158, 11, 0.03)',
};

const failAlertBoxStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
  background: 'rgba(239, 68, 68, 0.15)',
  border: '1px solid rgba(239, 68, 68, 0.3)',
  color: '#FCA5A5',
  padding: '12px',
  borderRadius: '6px',
  fontSize: '12.5px',
  marginTop: '10px',
};

const successBannerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
  background: 'rgba(16, 185, 129, 0.15)',
  border: '1px solid rgba(16, 185, 129, 0.3)',
  color: '#34D399',
  padding: '10px 14px',
  borderRadius: 'var(--radius-sm)',
  fontSize: '12.5px',
};

const resultsGridStyle: React.CSSProperties = {
  display: 'flex',
  gap: '24px',
  alignItems: 'stretch',
};

const emptyScoresStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  height: '200px',
  color: 'var(--text-muted)',
  fontSize: '13px',
};

const rbacRowContainerStyle: React.CSSProperties = {
  width: '100%',
};

const rbacPassBoxStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '14px',
  padding: '14px',
  background: 'rgba(16, 185, 129, 0.08)',
  border: '1px solid rgba(16, 185, 129, 0.25)',
  borderRadius: '8px',
};

const rbacFailBoxStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '14px',
  padding: '14px',
  background: 'rgba(239, 68, 68, 0.08)',
  border: '1px solid rgba(239, 68, 68, 0.25)',
  borderRadius: '8px',
};

const thresholdHeaderStyle: React.CSSProperties = {
  fontSize: '11px',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  color: 'var(--text-muted)',
  borderBottom: '1px solid var(--border)',
  paddingBottom: '6px',
  marginBottom: '4px',
};

const thresholdRowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  padding: '4px 0',
};
