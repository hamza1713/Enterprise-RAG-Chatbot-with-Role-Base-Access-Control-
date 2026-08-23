import React, { useState, useEffect } from 'react';
import client, { API_URL } from '../api/client';
import { useAuthStore } from '../store/authStore';
import type { RagasScores, EvalStatusResponse, RagasEvalRecord } from '../types';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  Cell,
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Legend,
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
  Search,
  Filter,
  Maximize2,
  X,
  RefreshCw,
  Award,
  Layers,
  ArrowUpDown,
  BookOpen,
} from 'lucide-react';

const ROLE_COLORS: Record<string, string> = {
  'c-level': '#F59E0B',
  'clevel': '#F59E0B',
  'hr': '#10B981',
  'finance': '#3B82F6',
  'engineering': '#A78BFA',
  'marketing': '#EC4899',
  'general': '#64748B',
};

const THRESHOLDS: Record<string, { pass: number; warn: number }> = {
  faithfulness: { pass: 0.75, warn: 0.85 },
  answer_relevancy: { pass: 0.70, warn: 0.75 },
  context_precision: { pass: 0.65, warn: 0.70 },
  context_recall: { pass: 0.70, warn: 0.75 },
  answer_correctness: { pass: 0.60, warn: 0.65 },
};

const checkMetricStatus = (metric: string, val: number | undefined): 'pass' | 'warn' | 'fail' | 'neutral' => {
  if (val === undefined || val === null) return 'neutral';
  const key = metric.toLowerCase().replace(/\s+/g, '_');
  const t = THRESHOLDS[key];
  if (!t) return 'neutral';
  
  if (val >= t.warn) return 'pass';
  if (val >= t.pass) return 'warn';
  return 'fail';
};

const getMetricColor = (status: 'pass' | 'warn' | 'fail' | 'neutral') => {
  switch (status) {
    case 'pass': return '#10B981';
    case 'warn': return '#F59E0B';
    case 'fail': return '#EF4444';
    default: return '#64748B';
  }
};

const getMetricBgClass = (status: 'pass' | 'warn' | 'fail' | 'neutral') => {
  switch (status) {
    case 'pass': return 'rgba(16, 185, 129, 0.1)';
    case 'warn': return 'rgba(245, 158, 11, 0.1)';
    case 'fail': return 'rgba(239, 68, 68, 0.1)';
    default: return 'rgba(255, 255, 255, 0.03)';
  }
};

const parseContexts = (contexts: string | string[] | undefined): string[] => {
  if (!contexts) return [];
  if (Array.isArray(contexts)) return contexts;
  const str = contexts.trim();
  if (str.startsWith('[') && str.endsWith(']')) {
    try {
      // Clean string representation of python list
      return JSON.parse(str.replace(/'/g, '"'));
    } catch {
      // Manual regex splitting on quotes
      const matches = str.match(/['"](.*?)['"]/g);
      if (matches) {
        return matches.map(m => m.replace(/^['"]|['"]$/g, ''));
      }
    }
  }
  return [str];
};

export default function EvaluationPage() {
  const { token } = useAuthStore();
  const [evalStatus, setEvalStatus] = useState<EvalStatusResponse | null>(null);
  const [, setLoading] = useState(false);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [triggerSuccess, setTriggerSuccess] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'dashboard' | 'roles' | 'records' | 'security'>('dashboard');

  // Trigger form state
  const [evalMode, setEvalMode] = useState<'full' | 'quality_only' | 'security_only'>('full');
  const [useBuiltinDataset, setUseBuiltinDataset] = useState(false);
  const [maxPerRole, setMaxPerRole] = useState(15);

  // Detailed records state
  const [records, setRecords] = useState<RagasEvalRecord[]>([]);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [selectedRecord, setSelectedRecord] = useState<RagasEvalRecord | null>(null);

  // Filters and sorting
  const [searchQuery, setSearchQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'pass' | 'warn' | 'fail'>('all');
  const [sortConfig, setSortConfig] = useState<{ key: string; direction: 'asc' | 'desc' } | null>(null);

  const fetchRecords = async () => {
    setRecordsLoading(true);
    try {
      const res = await client.get('/evaluate/records');
      setRecords(res.data.records || []);
    } catch (e) {
      console.error('Failed to fetch detailed evaluation records', e);
    } finally {
      setRecordsLoading(false);
    }
  };

  const fetchStatus = async (showLoader = true) => {
    if (showLoader) setLoading(true);
    try {
      const res = await client.get('/evaluate/status');
      setEvalStatus(res.data);
      // Fetch records if the system has ever been run (regardless of current running state)
      if (res.data?.status !== 'never_run') {
        fetchRecords();
      }
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
  };

  const scoresData = getChartData(evalStatus?.overall);
  const COLORS = ['#6366F1', '#8B5CF6', '#3B82F6', '#10B981', '#EC4899'];

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

  const getPassFailBadge = (pf: 'pass' | 'fail' | 'warn' | undefined) => {
    if (!pf) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
    if (pf === 'pass') {
      return <span style={{ color: '#34D399', fontWeight: 'bold', fontSize: '11px' }}>PASS</span>;
    } else if (pf === 'warn') {
      return <span style={{ color: '#FBBF24', fontWeight: 'bold', fontSize: '11px' }}>WARN</span>;
    } else {
      return <span style={{ color: '#F87171', fontWeight: 'bold', fontSize: '11px' }}>FAIL</span>;
    }
  };

  const getOverallRecordStatus = (rec: RagasEvalRecord) => {
    const metrics = ['faithfulness', 'answer_relevancy', 'context_precision', 'context_recall', 'answer_correctness'];
    let hasFail = false;
    let hasWarn = false;
    let hasAnyMetric = false;
    
    metrics.forEach(m => {
      const val = rec[m as keyof RagasEvalRecord] as number | undefined;
      if (val !== undefined && val !== null) {
        hasAnyMetric = true;
        const status = checkMetricStatus(m, val);
        if (status === 'fail') hasFail = true;
        if (status === 'warn') hasWarn = true;
      }
    });
    
    if (!hasAnyMetric) return 'pass';
    if (hasFail) return 'fail';
    if (hasWarn) return 'warn';
    return 'pass';
  };

  // Sorting handler
  const handleSort = (key: string) => {
    let direction: 'asc' | 'desc' = 'asc';
    if (sortConfig && sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setSortConfig({ key, direction });
  };

  // Get sorted and filtered records
  const getFilteredAndSortedRecords = () => {
    const filtered = records.filter(r => {
      const matchesSearch = 
        r.user_input.toLowerCase().includes(searchQuery.toLowerCase()) || 
        r.response.toLowerCase().includes(searchQuery.toLowerCase()) ||
        r.reference.toLowerCase().includes(searchQuery.toLowerCase());
        
      const matchesRole = roleFilter === 'all' || r.role.toLowerCase() === roleFilter.toLowerCase();
      
      const recStatus = getOverallRecordStatus(r);
      const matchesStatus = statusFilter === 'all' || recStatus === statusFilter;
      
      return matchesSearch && matchesRole && matchesStatus;
    });

    if (!sortConfig) return filtered;

    return [...filtered].sort((a: any, b: any) => {
      const aVal = a[sortConfig.key];
      const bVal = b[sortConfig.key];
      
      if (aVal === undefined || aVal === null) return 1;
      if (bVal === undefined || bVal === null) return -1;
      
      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return sortConfig.direction === 'asc' 
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }
      
      return sortConfig.direction === 'asc' ? aVal - bVal : bVal - aVal;
    });
  };

  // Fallback per_role calculation if not present in status
  const getPerRoleScores = (): Record<string, RagasScores> => {
    if (evalStatus?.per_role && Object.keys(evalStatus.per_role).length > 0) {
      return evalStatus.per_role;
    }
    
    if (records.length === 0) return {};
    
    const temp: Record<string, Record<string, number[]>> = {};
    const metrics = ['faithfulness', 'answer_relevancy', 'context_precision', 'context_recall', 'answer_correctness'];
    
    records.forEach(r => {
      if (!r.role) return;
      const role = r.role.toLowerCase();
      if (!temp[role]) temp[role] = {};
      
      metrics.forEach(m => {
        const val = r[m as keyof RagasEvalRecord] as number | undefined;
        if (val !== undefined && val !== null) {
          if (!temp[role][m]) temp[role][m] = [];
          temp[role][m].push(val);
        }
      });
    });
    
    const result: Record<string, RagasScores> = {};
    Object.entries(temp).forEach(([role, metricsData]) => {
      result[role] = {};
      Object.entries(metricsData).forEach(([m, vals]) => {
        if (vals.length > 0) {
          const sum = vals.reduce((a, b) => a + b, 0);
          result[role][m] = sum / vals.length;
        }
      });
    });
    
    return result;
  };

  const perRoleScores = getPerRoleScores();
  const rolesPresent = Object.keys(perRoleScores);
  const showRoleAnalysis = rolesPresent.length > 0;

  // Format Radar data
  const getRadarData = () => {
    const metricsList = [
      { key: 'faithfulness', name: 'Faithfulness' },
      { key: 'answer_relevancy', name: 'Answer Relevancy' },
      { key: 'context_precision', name: 'Context Precision' },
      { key: 'context_recall', name: 'Context Recall' },
      { key: 'answer_correctness', name: 'Answer Correctness' },
    ];
    
    return metricsList.map(m => {
      const item: any = { subject: m.name };
      Object.entries(perRoleScores).forEach(([role, scores]) => {
        const val = scores[m.key];
        item[role] = val ? Math.round(val * 100) : 0;
      });
      return item;
    });
  };

  const radarData = getRadarData();
  const filteredAndSortedRecords = getFilteredAndSortedRecords();
  const hasResults = evalStatus?.overall && Object.keys(evalStatus.overall).length > 0;

  const getTabStyle = (tabId: string): React.CSSProperties => {
    const isActive = activeTab === tabId;
    let isTabDisabled = false;
    if (tabId === 'roles') isTabDisabled = !showRoleAnalysis;
    if (tabId === 'records') isTabDisabled = records.length === 0;
    if (tabId === 'security') isTabDisabled = !evalStatus?.rbac_overall && evalStatus?.status !== 'completed';
    
    return {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '8px',
      padding: '10px 18px',
      borderRadius: 'var(--radius-sm)',
      background: isActive ? 'rgba(99, 102, 241, 0.12)' : 'transparent',
      color: isTabDisabled 
        ? 'rgba(255, 255, 255, 0.25)' 
        : (isActive ? '#818CF8' : 'var(--text-secondary)'),
      border: isActive ? '1px solid rgba(99, 102, 241, 0.25)' : '1px solid transparent',
      cursor: isTabDisabled ? 'not-allowed' : 'pointer',
      fontSize: '13.5px',
      fontWeight: '600',
      transition: 'var(--transition-smooth)',
      opacity: isTabDisabled ? 0.4 : 1,
    };
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header */}
      <div className="fs-header" style={{ marginBottom: '10px' }}>
        <h1 className="fs-title">📈 Evaluation Suite</h1>
        <p className="fs-subtitle">Trigger performance benchmarks (RAGAS quality indexes) and RBAC compliance security tests.</p>
      </div>

      {/* Tabs navigation */}
      <div style={tabsContainerStyle}>
        <button 
          style={getTabStyle('dashboard')} 
          onClick={() => setActiveTab('dashboard')}
        >
          <Activity size={15} />
          <span>Dashboard</span>
        </button>
        <button 
          style={getTabStyle('roles')} 
          onClick={() => !(!showRoleAnalysis) && setActiveTab('roles')}
          disabled={!showRoleAnalysis}
          title={!showRoleAnalysis ? 'No per-role evaluation scores available.' : ''}
        >
          <Layers size={15} />
          <span>Role Analysis</span>
          {!showRoleAnalysis && <span style={{ fontSize: '9px', opacity: 0.6 }}>(Locked)</span>}
        </button>
        <button 
          style={getTabStyle('records')} 
          onClick={() => !(records.length === 0) && setActiveTab('records')}
          disabled={records.length === 0}
          title={records.length === 0 ? 'No test records loaded.' : ''}
        >
          <BookOpen size={15} />
          <span>RAGAS Test Cases</span>
          {records.length > 0 && <span style={counterBadgeStyle}>{records.length}</span>}
        </button>
        <button 
          style={getTabStyle('security')} 
          onClick={() => !(!evalStatus?.rbac_overall && evalStatus?.status !== 'completed') && setActiveTab('security')}
          disabled={!evalStatus?.rbac_overall && evalStatus?.status !== 'completed'}
        >
          <ShieldCheck size={15} />
          <span>RBAC Security</span>
        </button>
      </div>

      {/* ACTIVE TAB: DASHBOARD */}
      {activeTab === 'dashboard' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <div style={gridStyle}>
            {/* Trigger card */}
            <div className="fs-card" style={cardStyle}>
              <div style={cardTitleContainerStyle}>
                <Play size={18} color="var(--primary)" />
                <h2 style={cardTitleStyle}>Run system evaluation</h2>
              </div>
              <p style={cardSubtitleStyle}>Kick off background metrics evaluations. Runs real RAG pipelines for target roles.</p>

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
                  <RefreshCw size={16} className={triggerLoading ? 'spin-animation' : ''} />
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
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', width: '100%' }}>
                      <div className="chat-thinking" style={{ display: 'flex', justifyContent: 'center' }}>
                        <span></span>
                        <span></span>
                        <span></span>
                      </div>
                      <span style={{ fontSize: '12px', color: '#FBBF24', fontWeight: '500' }}>
                        Executing RAGAS quality benchmarks...
                      </span>
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
                    <span>Open HTML Report in New Tab</span>
                    <ExternalLink size={12} />
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Results Overview (Bar chart + overall thresholds) */}
          {hasResults && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', width: '100%' }}>
              <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '10px 0' }} />
              {evalStatus?.status !== 'completed' && (
                <div style={{ 
                  fontSize: '12px', 
                  color: '#FBBF24', 
                  background: 'rgba(245, 158, 11, 0.05)', 
                  border: '1px solid rgba(245, 158, 11, 0.18)', 
                  padding: '10px 14px', 
                  borderRadius: '8px', 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '8px' 
                }}>
                  <AlertTriangle size={14} />
                  <span>Displaying results from the last completed run. A new run is in progress or the current run was interrupted.</span>
                </div>
              )}
              <div style={resultsGridStyle}>
                {/* Recharts Bar chart */}
                <div className="fs-card" style={{ flex: 1, padding: '24px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                    <h3 style={{ fontSize: '14.5px', fontWeight: 700, margin: 0 }}>📊 Overall RAGAS Quality Metrics</h3>
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Higher is better (0-100%)</span>
                  </div>
                  
                  {scoresData.length > 0 ? (
                    <div style={{ width: '100%', height: '260px' }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={scoresData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                          <XAxis dataKey="name" stroke="#64748B" fontSize={11} tickLine={false} />
                          <YAxis domain={[0, 100]} stroke="#64748B" fontSize={11} tickLine={false} />
                          <RechartsTooltip 
                            contentStyle={{ background: '#0a0d24', border: '1px solid var(--border)', borderRadius: '6px' }}
                            labelStyle={{ color: '#fff', fontWeight: 'bold' }}
                            itemStyle={{ color: 'var(--primary-hover)' }}
                            formatter={(value) => [`${value}%`, 'Score']}
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

                {/* RAGAS Thresholds info card */}
                <div className="fs-card" style={{ width: '380px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Award size={18} color="var(--primary)" />
                    <h3 style={{ fontSize: '14.5px', fontWeight: 700, margin: 0 }}>Metric Threshold Gates</h3>
                  </div>
                  <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: 0 }}>
                    Benchmarked against strict enterprise-grade quality thresholds.
                  </p>

                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '4px' }}>
                    <div style={thresholdHeaderStyle}>Metric Quality Thresholds</div>
                    
                    {evalStatus?.overall && Object.entries(evalStatus.overall).map(([metric, val], idx) => {
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
      )}

      {/* ACTIVE TAB: ROLE ANALYSIS */}
      {activeTab === 'roles' && showRoleAnalysis && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          <div style={resultsGridStyle}>
            {/* Radar chart */}
            <div className="fs-card" style={{ flex: 1, padding: '24px' }}>
              <h3 style={{ fontSize: '14.5px', fontWeight: 700, marginBottom: '20px' }}>🕸️ Per-Role Metrics Overlay</h3>
              <div style={{ width: '100%', height: '360px' }}>
                <ResponsiveContainer width="100%" height="100%">
                  <RadarChart cx="50%" cy="50%" outerRadius="75%" data={radarData}>
                    <PolarGrid stroke="rgba(99, 102, 241, 0.15)" />
                    <PolarAngleAxis dataKey="subject" stroke="#94A3B8" fontSize={11} />
                    <PolarRadiusAxis angle={30} domain={[0, 100]} stroke="#64748B" fontSize={10} />
                    {rolesPresent.map((role) => (
                      <Radar
                        key={role}
                        name={role.toUpperCase()}
                        dataKey={role}
                        stroke={ROLE_COLORS[role.toLowerCase()] || '#8B5CF6'}
                        fill={ROLE_COLORS[role.toLowerCase()] || '#8B5CF6'}
                        fillOpacity={0.12}
                      />
                    ))}
                    <Legend />
                    <RechartsTooltip 
                      contentStyle={{ background: '#0a0d24', border: '1px solid var(--border)', borderRadius: '6px' }}
                      labelStyle={{ color: '#fff', fontWeight: 'bold' }}
                      formatter={(value, name) => [`${value}%`, name]}
                    />
                  </RadarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Threshold explanations */}
            <div className="fs-card" style={{ width: '380px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <h3 style={{ fontSize: '14.5px', fontWeight: 700, margin: 0 }}>Quality Metrics Glossary</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', maxHeight: '360px', paddingRight: '4px' }}>
                <div style={glossaryItemStyle}>
                  <strong style={{ color: '#6366F1' }}>Faithfulness:</strong>
                  <p style={{ margin: '2px 0 0 0', fontSize: '11.5px', color: 'var(--text-secondary)' }}>Is the answer grounded strictly in the retrieved context? Catches hallucinations.</p>
                </div>
                <div style={glossaryItemStyle}>
                  <strong style={{ color: '#8B5CF6' }}>Answer Relevancy:</strong>
                  <p style={{ margin: '2px 0 0 0', fontSize: '11.5px', color: 'var(--text-secondary)' }}>Does the answer address the question directly without containing redundant text?</p>
                </div>
                <div style={glossaryItemStyle}>
                  <strong style={{ color: '#3B82F6' }}>Context Precision:</strong>
                  <p style={{ margin: '2px 0 0 0', fontSize: '11.5px', color: 'var(--text-secondary)' }}>Are the retrieved document chunks highly relevant to the question asked?</p>
                </div>
                <div style={glossaryItemStyle}>
                  <strong style={{ color: '#10B981' }}>Context Recall:</strong>
                  <p style={{ margin: '2px 0 0 0', fontSize: '11.5px', color: 'var(--text-secondary)' }}>Does the context cover all facts needed to construct the reference answer?</p>
                </div>
                <div style={glossaryItemStyle}>
                  <strong style={{ color: '#EC4899' }}>Answer Correctness:</strong>
                  <p style={{ margin: '2px 0 0 0', fontSize: '11.5px', color: 'var(--text-secondary)' }}>Measures the factual and semantic accuracy compared to the reference ground truth.</p>
                </div>
              </div>
            </div>
          </div>

          {/* Comparative Matrix Heat-grid */}
          <div className="fs-card" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '14.5px', fontWeight: 700, marginBottom: '16px' }}>📊 Department-wise Performance Matrix</h3>
            
            <div className="fs-table-wrap" style={{ marginTop: '0px' }}>
              <table className="fs-table">
                <thead>
                  <tr>
                    <th>Role / Department</th>
                    <th>Faithfulness</th>
                    <th>Answer Relevancy</th>
                    <th>Context Precision</th>
                    <th>Context Recall</th>
                    <th>Answer Correctness</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(perRoleScores).map(([role, scores]: [string, any]) => (
                    <tr key={role}>
                      <td style={{ fontWeight: 'bold' }}>
                        <span style={{ 
                          display: 'inline-block', 
                          width: '8px', 
                          height: '8px', 
                          borderRadius: '50%', 
                          background: ROLE_COLORS[role.toLowerCase()] || '#64748B',
                          marginRight: '8px'
                        }}></span>
                        {role.toUpperCase()}
                      </td>
                      {['faithfulness', 'answer_relevancy', 'context_precision', 'context_recall', 'answer_correctness'].map((metric) => {
                        const score = scores[metric];
                        if (score === undefined || score === null) {
                          return <td key={metric} style={{ color: 'var(--text-muted)', textAlign: 'center' }}>—</td>;
                        }
                        const status = checkMetricStatus(metric, score);
                        return (
                          <td 
                            key={metric}
                            style={{ 
                              color: getMetricColor(status), 
                              background: getMetricBgClass(status),
                              fontWeight: '600',
                              fontFamily: 'var(--font-mono)'
                            }}
                          >
                            {(score * 100).toFixed(1)}%
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ACTIVE TAB: RAGAS DETAILED RECORDS */}
      {activeTab === 'records' && (
        <div className="fs-card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          {/* Filters header */}
          <div style={{ display: 'flex', gap: '16px', alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ position: 'relative', flex: 1, minWidth: '240px' }}>
              <Search size={16} style={searchIconStyle} />
              <input
                type="text"
                placeholder="Search questions, references, or responses..."
                className="fs-input"
                style={{ paddingLeft: '40px' }}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            
            <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Filter size={14} color="var(--text-muted)" />
                <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Role:</span>
              </div>
              <select
                className="fs-input"
                style={{ width: '130px', padding: '8px 12px', height: '38px' }}
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value)}
              >
                <option value="all">All Roles</option>
                {Array.from(new Set(records.map(r => r.role))).map(role => (
                  <option key={role} value={role}>{role.toUpperCase()}</option>
                ))}
              </select>
            </div>

            <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
              <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Status:</span>
              <select
                className="fs-input"
                style={{ width: '130px', padding: '8px 12px', height: '38px' }}
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as any)}
              >
                <option value="all">All Statuses</option>
                <option value="pass">PASS Only</option>
                <option value="warn">WARN Only</option>
                <option value="fail">FAIL Only</option>
              </select>
            </div>

            <button 
              className="fs-btn fs-btn-secondary" 
              style={{ height: '38px', padding: '0 16px' }}
              onClick={fetchRecords}
              disabled={recordsLoading}
            >
              <RefreshCw size={14} className={recordsLoading ? 'spin-animation' : ''} />
              <span>Refresh</span>
            </button>
          </div>

          {/* Test cases table */}
          {recordsLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '200px' }}>
              <div className="chat-thinking">
                <span></span>
                <span></span>
                <span></span>
              </div>
              <span style={{ marginLeft: '10px', color: 'var(--text-muted)' }}>Loading evaluation test runs...</span>
            </div>
          ) : filteredAndSortedRecords.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
              No evaluation records found matching your filters.
            </div>
          ) : (
            <div className="fs-table-wrap" style={{ marginTop: '0px', maxHeight: '450px' }}>
              <table className="fs-table">
                <thead>
                  <tr>
                    <th onClick={() => handleSort('user_input')} style={sortableHeaderStyle}>
                      <span>Question</span>
                      <ArrowUpDown size={12} style={{ opacity: 0.7 }} />
                    </th>
                    <th onClick={() => handleSort('role')} style={sortableHeaderStyle}>
                      <span>Role</span>
                      <ArrowUpDown size={12} style={{ opacity: 0.7 }} />
                    </th>
                    <th onClick={() => handleSort('faithfulness')} style={sortableHeaderStyle}>
                      <span>Faithfulness</span>
                      <ArrowUpDown size={12} style={{ opacity: 0.7 }} />
                    </th>
                    <th onClick={() => handleSort('answer_relevancy')} style={sortableHeaderStyle}>
                      <span>Relevancy</span>
                      <ArrowUpDown size={12} style={{ opacity: 0.7 }} />
                    </th>
                    <th onClick={() => handleSort('context_precision')} style={sortableHeaderStyle}>
                      <span>Precision</span>
                      <ArrowUpDown size={12} style={{ opacity: 0.7 }} />
                    </th>
                    <th onClick={() => handleSort('context_recall')} style={sortableHeaderStyle}>
                      <span>Recall</span>
                      <ArrowUpDown size={12} style={{ opacity: 0.7 }} />
                    </th>
                    <th onClick={() => handleSort('answer_correctness')} style={sortableHeaderStyle}>
                      <span>Correctness</span>
                      <ArrowUpDown size={12} style={{ opacity: 0.7 }} />
                    </th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAndSortedRecords.map((record, index) => {
                    const borderLeftColor = ROLE_COLORS[record.role.toLowerCase()] || '#64748B';
                    return (
                      <tr key={index}>
                        <td 
                          style={{ 
                            maxWidth: '280px', 
                            overflow: 'hidden', 
                            textOverflow: 'ellipsis', 
                            whiteSpace: 'nowrap',
                            borderLeft: `3px solid ${borderLeftColor}`,
                            paddingLeft: '12px'
                          }} 
                          title={record.user_input}
                        >
                          {record.user_input}
                        </td>
                        <td>
                          <span style={{ 
                            display: 'inline-block',
                            padding: '2px 8px',
                            borderRadius: '4px',
                            fontSize: '10px',
                            fontWeight: 'bold',
                            background: `${ROLE_COLORS[record.role.toLowerCase()]}20`,
                            color: ROLE_COLORS[record.role.toLowerCase()] || '#fff',
                            border: `1px solid ${ROLE_COLORS[record.role.toLowerCase()]}40`
                          }}>
                            {record.role.toUpperCase()}
                          </span>
                        </td>
                        {['faithfulness', 'answer_relevancy', 'context_precision', 'context_recall', 'answer_correctness'].map((met) => {
                          const val = record[met as keyof RagasEvalRecord] as number | undefined;
                          if (val === undefined || val === null) {
                            return <td key={met} style={{ color: 'var(--text-muted)', textAlign: 'center' }}>—</td>;
                          }
                          const metStatus = checkMetricStatus(met, val);
                          return (
                            <td key={met} style={{ color: getMetricColor(metStatus), fontFamily: 'var(--font-mono)' }}>
                              {val.toFixed(2)}
                            </td>
                          );
                        })}
                        <td>
                          <button 
                            className="fs-btn fs-btn-secondary" 
                            style={{ padding: '4px 8px', fontSize: '11px', height: '26px' }}
                            onClick={() => setSelectedRecord(record)}
                          >
                            <Maximize2 size={11} />
                            <span>View Details</span>
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
      )}

      {/* ACTIVE TAB: RBAC SECURITY */}
      {activeTab === 'security' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {/* RBAC overall badge */}
          <div className="fs-card" style={{ padding: '24px' }}>
            <div style={rbacRowContainerStyle}>
              {evalStatus?.rbac_overall === 'Passed' ? (
                <div style={rbacPassBoxStyle}>
                  <ShieldCheck size={40} color="#34D399" />
                  <div>
                    <div style={{ fontWeight: 'bold', fontSize: '16px', color: '#fff' }}>RBAC Strict Security Policy Verified</div>
                    <div style={{ fontSize: '13px', color: '#CBD5E1', marginTop: '4px' }}>
                      All automated access control checks passed. There were zero data leakage events or unauthorized operations detected.
                    </div>
                  </div>
                </div>
              ) : (
                <div style={rbacFailBoxStyle}>
                  <ShieldAlert size={40} color="#F87171" />
                  <div>
                    <div style={{ fontWeight: 'bold', fontSize: '16px', color: '#fff' }}>RBAC Security Breaches Detected!</div>
                    <div style={{ fontSize: '13px', color: '#FCA5A5', marginTop: '4px' }}>
                      Critical authorization flaws found. Cross-department queries retrieved documents that should be inaccessible to those roles.
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Security details checklist */}
          <div className="fs-card" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
              <ShieldCheck size={20} color="var(--primary)" />
              <h3 style={{ fontSize: '14.5px', fontWeight: 700, margin: 0 }}>RBAC Authorization Checks List</h3>
            </div>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={securityCheckItemStyle}>
                <CheckCircle size={16} color="#34D399" />
                <div>
                  <strong style={{ fontSize: '13px' }}>Unauthorised Access Blocking</strong>
                  <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                    Verifies that HR/Finance roles cannot retrieve documents belonging to other isolated departments.
                  </p>
                </div>
              </div>
              <div style={securityCheckItemStyle}>
                <CheckCircle size={16} color="#34D399" />
                <div>
                  <strong style={{ fontSize: '13px' }}>Authorised Access Allowance</strong>
                  <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                    Ensures that role-compliant retrieval requests correctly fetch department-specific documents.
                  </p>
                </div>
              </div>
              <div style={securityCheckItemStyle}>
                <CheckCircle size={16} color="#34D399" />
                <div>
                  <strong style={{ fontSize: '13px' }}>C-Level Role Privilege Escapes</strong>
                  <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                    Ensures the executive (C-level) role retains full visibility, bypassing vector filters to search all databases.
                  </p>
                </div>
              </div>
              <div style={securityCheckItemStyle}>
                <CheckCircle size={16} color="#34D399" />
                <div>
                  <strong style={{ fontSize: '13px' }}>General Document Availability</strong>
                  <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                    Validates that public/general documents are accessible by users belonging to any department.
                  </p>
                </div>
              </div>
              <div style={securityCheckItemStyle}>
                <CheckCircle size={16} color="#34D399" />
                <div>
                  <strong style={{ fontSize: '13px' }}>Retriever Filter Enforcements</strong>
                  <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                    Validates that the ChromaDB metadata queries are hardcoded with filters and cannot be manipulated at runtime.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* DETAIL MODAL DRAWER OVERLAY */}
      {selectedRecord && (
        <div style={modalOverlayStyle}>
          <div className="fs-card" style={modalContentStyle}>
            {/* Modal header */}
            <div style={modalHeaderStyle}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ 
                  display: 'inline-block',
                  padding: '3px 10px',
                  borderRadius: '4px',
                  fontSize: '11px',
                  fontWeight: 'bold',
                  background: `${ROLE_COLORS[selectedRecord.role.toLowerCase()]}20`,
                  color: ROLE_COLORS[selectedRecord.role.toLowerCase()] || '#fff',
                  border: `1px solid ${ROLE_COLORS[selectedRecord.role.toLowerCase()]}40`
                }}>
                  {selectedRecord.role.toUpperCase()}
                </span>
                <h3 style={{ fontSize: '16px', fontWeight: 700, margin: 0, color: '#fff' }}>Test Case Details</h3>
              </div>
              <button style={closeButtonStyle} onClick={() => setSelectedRecord(null)}>
                <X size={18} />
              </button>
            </div>

            {/* Modal body */}
            <div style={modalBodyStyle}>
              {/* Question summary */}
              <div style={modalQuestionBlockStyle}>
                <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Evaluation Question</span>
                <div style={{ fontSize: '14.5px', fontWeight: '600', color: '#fff', marginTop: '4px' }}>
                  {selectedRecord.user_input}
                </div>
              </div>

              {/* RAGAS scores summary */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Sample RAGAS Scores</span>
                <div style={modalScoresGridStyle}>
                  {['faithfulness', 'answer_relevancy', 'context_precision', 'context_recall', 'answer_correctness'].map((met) => {
                    const score = selectedRecord[met as keyof RagasEvalRecord] as number | undefined;
                    if (score === undefined || score === null) return null;
                    const status = checkMetricStatus(met, score);
                    const color = getMetricColor(status);
                    return (
                      <div key={met} style={modalScoreCardStyle}>
                        <div style={{ fontSize: '11px', textTransform: 'capitalize', color: 'var(--text-secondary)' }}>
                          {met.replace('_', ' ')}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', marginTop: '2px' }}>
                          <span style={{ fontSize: '20px', fontWeight: 'bold', fontFamily: 'var(--font-mono)', color }}>
                            {score.toFixed(2)}
                          </span>
                          <span style={{ fontSize: '10px', fontWeight: 'bold', color }}>
                            {status.toUpperCase()}
                          </span>
                        </div>
                        <div style={miniBarTrackStyle}>
                          <div style={{ 
                            height: '100%', 
                            borderRadius: '2px', 
                            background: color, 
                            width: `${score * 100}%` 
                          }}></div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Outputs comparison */}
              <div style={modalOutputGridStyle}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Award size={14} color="#10B981" />
                    <strong style={{ fontSize: '12px', color: '#fff' }}>Reference Answer (Ground Truth)</strong>
                  </div>
                  <div style={textDisplayBoxStyle}>
                    {selectedRecord.reference}
                  </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Activity size={14} color="#6366F1" />
                    <strong style={{ fontSize: '12px', color: '#fff' }}>Generated RAG Response</strong>
                  </div>
                  <div style={textDisplayBoxStyle}>
                    {selectedRecord.response}
                  </div>
                </div>
              </div>

              {/* Retrieved Context chunks */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <FileText size={14} color="#8B5CF6" />
                  <strong style={{ fontSize: '12px', color: '#fff' }}>Retrieved Context Chunks</strong>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '180px', overflowY: 'auto' }}>
                  {parseContexts(selectedRecord.retrieved_contexts).map((chunk, idx) => (
                    <div 
                      key={idx} 
                      style={{
                        ...chunkBoxStyle, 
                        borderLeftColor: ROLE_COLORS[selectedRecord.role.toLowerCase()] || '#6366F1'
                      }}
                    >
                      <div style={chunkHeaderStyle}>Chunk #{idx + 1}</div>
                      <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
                        {chunk}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// STYLES
const tabsContainerStyle: React.CSSProperties = {
  display: 'flex',
  gap: '8px',
  borderBottom: '1px solid var(--border)',
  paddingBottom: '8px',
  marginBottom: '4px',
};



const counterBadgeStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'rgba(99, 102, 241, 0.25)',
  color: 'var(--primary-hover)',
  borderRadius: '10px',
  padding: '1px 6px',
  fontSize: '10px',
  fontWeight: 'bold',
  marginLeft: '4px',
};

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
  fontSize: '12.5px',
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
  gap: '16px',
  padding: '18px',
  background: 'rgba(16, 185, 129, 0.06)',
  border: '1px solid rgba(16, 185, 129, 0.2)',
  borderRadius: '10px',
};

const rbacFailBoxStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '16px',
  padding: '18px',
  background: 'rgba(239, 68, 68, 0.06)',
  border: '1px solid rgba(239, 68, 68, 0.2)',
  borderRadius: '10px',
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

const glossaryItemStyle: React.CSSProperties = {
  padding: '10px',
  borderRadius: '6px',
  background: 'rgba(255, 255, 255, 0.02)',
  border: '1px solid var(--border)',
};

const searchIconStyle: React.CSSProperties = {
  position: 'absolute',
  left: '14px',
  top: '50%',
  transform: 'translateY(-50%)',
  color: 'var(--text-muted)',
};

const sortableHeaderStyle: React.CSSProperties = {
  cursor: 'pointer',
  userSelect: 'none',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: '8px',
};

const securityCheckItemStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: '12px',
  padding: '12px',
  borderRadius: '6px',
  background: 'rgba(255,255,255,0.01)',
  border: '1px solid rgba(255,255,255,0.03)',
};

// Modal specific styling
const modalOverlayStyle: React.CSSProperties = {
  position: 'fixed',
  top: 0,
  left: 0,
  right: 0,
  bottom: 0,
  background: 'rgba(2, 4, 15, 0.8)',
  backdropFilter: 'blur(8px)',
  zIndex: 1000,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
};

const modalContentStyle: React.CSSProperties = {
  width: '90%',
  maxWidth: '900px',
  maxHeight: '90vh',
  padding: '24px',
  display: 'flex',
  flexDirection: 'column',
  gap: '18px',
  overflowY: 'auto',
  border: '1px solid var(--border-hover)',
  boxShadow: '0 20px 50px rgba(0,0,0,0.5)',
};

const modalHeaderStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  borderBottom: '1px solid var(--border)',
  paddingBottom: '12px',
};

const closeButtonStyle: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  color: 'var(--text-secondary)',
  cursor: 'pointer',
  padding: '4px',
  borderRadius: '4px',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  transition: 'var(--transition-smooth)',
};

const modalBodyStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '16px',
};

const modalQuestionBlockStyle: React.CSSProperties = {
  background: 'rgba(99, 102, 241, 0.05)',
  border: '1px solid rgba(99, 102, 241, 0.15)',
  padding: '12px 16px',
  borderRadius: '8px',
};

const modalScoresGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
  gap: '10px',
};

const modalScoreCardStyle: React.CSSProperties = {
  background: 'rgba(255,255,255,0.02)',
  border: '1px solid var(--border)',
  borderRadius: '6px',
  padding: '10px 12px',
};

const miniBarTrackStyle: React.CSSProperties = {
  height: '4px',
  background: 'rgba(255,255,255,0.05)',
  borderRadius: '2px',
  marginTop: '8px',
  overflow: 'hidden',
};

const modalOutputGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr',
  gap: '16px',
};

const textDisplayBoxStyle: React.CSSProperties = {
  padding: '12px',
  background: 'rgba(5, 7, 20, 0.4)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  fontSize: '12px',
  lineHeight: '1.6',
  color: 'var(--text-secondary)',
  maxHeight: '160px',
  overflowY: 'auto',
};

const chunkBoxStyle: React.CSSProperties = {
  padding: '10px 14px',
  background: 'rgba(5, 7, 20, 0.25)',
  border: '1px solid var(--border)',
  borderLeftWidth: '4px',
  borderRadius: '6px',
};

const chunkHeaderStyle: React.CSSProperties = {
  fontSize: '10px',
  fontWeight: 'bold',
  textTransform: 'uppercase',
  color: 'var(--text-muted)',
  marginBottom: '4px',
};

