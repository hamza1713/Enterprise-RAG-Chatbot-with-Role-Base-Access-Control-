import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { Activity, BookOpen, Layers, ShieldCheck } from 'lucide-react';
import client from '../api/client';
import { cancelJob } from '../api/jobs';
import AuditObservabilityTab from '../components/evaluation/AuditObservabilityTab';
import EvalDashboardTab from '../components/evaluation/EvalDashboardTab';
import EvalRecordsTab from '../components/evaluation/EvalRecordsTab';
import EvalRolesTab from '../components/evaluation/EvalRolesTab';
import EvalSecurityTab from '../components/evaluation/EvalSecurityTab';
import { METRIC_KEYS } from '../components/evaluation/evalHelpers';
import type { EvalStatusResponse, RagasEvalRecord, RagasScores } from '../types';

type EvalTab = 'dashboard' | 'roles' | 'records' | 'security' | 'audit';

export default function EvaluationPage() {
  const [reportError, setReportError] = useState('');
  const [evalStatus, setEvalStatus] = useState<EvalStatusResponse | null>(null);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [triggerSuccess, setTriggerSuccess] = useState<string | null>(null);
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<EvalTab>('dashboard');

  const [evalMode, setEvalMode] = useState<'full' | 'quality_only' | 'security_only'>('full');
  const [useBuiltinDataset, setUseBuiltinDataset] = useState(false);
  const [maxPerRole, setMaxPerRole] = useState(15);

  const [records, setRecords] = useState<RagasEvalRecord[]>([]);
  const [recordsLoading, setRecordsLoading] = useState(false);

  const fetchRecords = useCallback(async () => {
    setRecordsLoading(true);
    try {
      const res = await client.get('/evaluate/records');
      setRecords(res.data.records || []);
    } catch (err) {
      console.error('Failed to fetch detailed evaluation records', err);
    } finally {
      setRecordsLoading(false);
    }
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await client.get<EvalStatusResponse>('/evaluate/status');
      setEvalStatus(res.data);
      if (res.data?.status !== 'never_run') {
        void fetchRecords();
      }
    } catch (err) {
      console.error('Failed to fetch evaluation status', err);
    }
  }, [fetchRecords]);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  const isEvalActive = evalStatus?.status === 'queued' || evalStatus?.status === 'running';

  useEffect(() => {
    if (!isEvalActive) return;
    const interval = setInterval(() => {
      void fetchStatus();
    }, 4000);
    return () => clearInterval(interval);
  }, [isEvalActive, fetchStatus]);

  const handleCancelEval = async () => {
    if (!evalStatus?.job_id) return;
    setTriggerLoading(true);
    setTriggerError(null);
    setTriggerSuccess(null);
    try {
      await cancelJob(evalStatus.job_id);
      setTriggerSuccess('Cancellation requested for active evaluation run.');
      void fetchStatus();
    } catch (err: any) {
      setTriggerError(err?.response?.data?.detail || 'Could not cancel evaluation.');
    } finally {
      setTriggerLoading(false);
    }
  };

  const handleTriggerEval = async (e: React.FormEvent) => {
    e.preventDefault();
    setTriggerLoading(true);
    setTriggerSuccess(null);
    setTriggerError(null);
    try {
      const res = await client.post('/evaluate', {
        mode: evalMode,
        max_per_role: maxPerRole,
        use_builtin_dataset: useBuiltinDataset,
      });
      setTriggerSuccess(res.data.message || 'Evaluation started in background.');
      void fetchStatus();
      setTimeout(() => {
        setTriggerSuccess(null);
      }, 3000);
    } catch (err: any) {
      setTriggerError(err?.response?.data?.detail || 'Failed to start evaluation.');
    } finally {
      setTriggerLoading(false);
    }
  };

  const handleOpenHtmlReport = async () => {
    setReportError('');
    try {
      const response = await client.get('/evaluate/report', { responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([response.data], { type: 'text/html' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'finsight-evaluation-report.html';
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch {
      setReportError('The report could not be downloaded. Run an evaluation or try again.');
    }
  };

  const perRoleScores: Record<string, RagasScores> = (() => {
    if (evalStatus?.per_role && Object.keys(evalStatus.per_role).length > 0) {
      return evalStatus.per_role;
    }
    if (records.length === 0) return {};
    const temp: Record<string, Record<string, number[]>> = {};
    records.forEach((r) => {
      if (!r.role) return;
      const role = r.role.toLowerCase();
      if (!temp[role]) temp[role] = {};
      METRIC_KEYS.forEach((m) => {
        const val = r[m as keyof RagasEvalRecord] as number | undefined;
        if (val !== undefined && val !== null) {
          if (!temp[role][m]) temp[role][m] = [];
          temp[role][m].push(val);
        }
      });
    });
    const out: Record<string, RagasScores> = {};
    Object.entries(temp).forEach(([role, map]) => {
      out[role] = {};
      Object.entries(map).forEach(([m, vals]) => {
        if (vals.length > 0) out[role][m] = vals.reduce((a, b) => a + b, 0) / vals.length;
      });
    });
    return out;
  })();

  const showRoleAnalysis = Object.keys(perRoleScores).length > 0;
  const securityEnabled = Boolean(evalStatus?.rbac_overall || evalStatus?.status === 'completed');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div className="fs-header" style={{ marginBottom: '6px' }}>
        <h1 className="fs-title">Quality, Security & Audit Governance</h1>
        {reportError && (
          <div className="form-error" role="alert">
            {reportError}
          </div>
        )}
        <p className="fs-subtitle">
          Monitor RAGAS quality gates, ReBAC/OWASP red-team readiness, and immutable SOC 2 / EU AI Act audit logs.
        </p>
      </div>

      <div className="fs-tabs" role="tablist" aria-label="Evaluation and Audit Views">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'dashboard'}
          className={`fs-tab-btn${activeTab === 'dashboard' ? ' active' : ''}`}
          onClick={() => setActiveTab('dashboard')}
        >
          <Activity size={15} />
          <span>Dashboard</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'roles'}
          className={`fs-tab-btn${activeTab === 'roles' ? ' active' : ''}`}
          disabled={!showRoleAnalysis}
          onClick={() => showRoleAnalysis && setActiveTab('roles')}
        >
          <Layers size={15} />
          <span>Role Analysis</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'records'}
          className={`fs-tab-btn${activeTab === 'records' ? ' active' : ''}`}
          disabled={records.length === 0}
          onClick={() => records.length > 0 && setActiveTab('records')}
        >
          <BookOpen size={15} />
          <span>RAGAS Test Cases {records.length > 0 ? `(${records.length})` : ''}</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'security'}
          className={`fs-tab-btn${activeTab === 'security' ? ' active' : ''}`}
          disabled={!securityEnabled}
          onClick={() => securityEnabled && setActiveTab('security')}
        >
          <ShieldCheck size={15} />
          <span>RBAC Security</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'audit'}
          className={`fs-tab-btn${activeTab === 'audit' ? ' active' : ''}`}
          onClick={() => setActiveTab('audit')}
        >
          <ShieldCheck size={15} />
          <span>Audit & Observability</span>
        </button>
      </div>

      {activeTab === 'dashboard' && (
        <EvalDashboardTab
          evalStatus={evalStatus}
          evalMode={evalMode}
          setEvalMode={setEvalMode}
          useBuiltinDataset={useBuiltinDataset}
          setUseBuiltinDataset={setUseBuiltinDataset}
          maxPerRole={maxPerRole}
          setMaxPerRole={setMaxPerRole}
          triggerLoading={triggerLoading}
          triggerSuccess={triggerSuccess}
          triggerError={triggerError}
          isEvalActive={isEvalActive}
          onTriggerEval={handleTriggerEval}
          onCancelEval={handleCancelEval}
          onOpenHtmlReport={handleOpenHtmlReport}
        />
      )}

      {activeTab === 'roles' && showRoleAnalysis && <EvalRolesTab perRoleScores={perRoleScores} />}

      {activeTab === 'records' && (
        <EvalRecordsTab records={records} recordsLoading={recordsLoading} onRefresh={fetchRecords} />
      )}

      {activeTab === 'security' && <EvalSecurityTab rbacOverall={evalStatus?.rbac_overall} />}

      {activeTab === 'audit' && <AuditObservabilityTab />}
    </div>
  );
}
