import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import client from '../../api/client';
import * as auditApi from '../../api/audit';
import EvalSecurityTab from '../evaluation/EvalSecurityTab';
import EvaluationPage from '../../pages/EvaluationPage';

describe('Phase 3 Evaluation & Governance UI', () => {
  it('renders EvaluationPage tabs cleanly and switches to Audit & Observability KPIs', async () => {
    const getSpy = vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
      if (url === '/evaluate/status') {
        return {
          data: {
            status: 'completed',
            rbac_overall: 'PASS',
            overall: { faithfulness: 0.91, answer_relevancy: 0.88 },
            pass_fail: { faithfulness: 'pass', answer_relevancy: 'pass' },
            report_available: true,
          },
        } as any;
      }
      if (url === '/evaluate/records') {
        return { data: { records: [] } } as any;
      }
      throw new Error(`Unexpected GET ${url}`);
    });

    const summarySpy = vi.spyOn(auditApi, 'fetchAuditSummary').mockResolvedValue({
      window_days: 30,
      total_events: 42,
      chat_turns: 30,
      blocked_injections: 3,
      pii_redactions: 2,
      sql_executions: 10,
      sql_retries: 1,
      sql_retry_rate: 0.1,
      avg_latency_ms: 340,
      p95_latency_ms: 780,
      total_input_tokens: 4000,
      total_output_tokens: 1500,
      outcomes: { allow: 37, block: 3, redact: 2 },
      event_types: { chat_turn: 30 },
    });

    const logsSpy = vi.spyOn(auditApi, 'fetchAuditLogs').mockResolvedValue({
      total: 1,
      limit: 50,
      offset: 0,
      records: [
        {
          id: 1,
          event_id: 'evt-1',
          request_id: 'req-0001-abcd',
          thread_id: 'th-1',
          username: 'finance_user',
          user_role: 'Finance',
          auth_provider: 'local',
          event_type: 'chat_turn',
          mode: 'RAG',
          authorized_doc_count: 2,
          authorized_dataset_names: ['finance_data'],
          cited_doc_ids: [1],
          cited_chunk_ids: ['c1'],
          sql_retries: 0,
          guardrail_flags: [],
          outcome: 'allow',
          latency_ms: 310,
          input_tokens: 200,
          output_tokens: 90,
          ai_disclosure: true,
          created_at: '2026-11-16T10:00:00Z',
        },
      ],
    });

    const exportSpy = vi.spyOn(auditApi, 'downloadAuditExport').mockResolvedValue();

    render(<EvaluationPage />);
    expect(await screen.findByText('Quality, Security & Audit Governance')).toBeInTheDocument();

    const auditTabBtn = screen.getByRole('tab', { name: /Audit & Observability/i });
    fireEvent.click(auditTabBtn);

    await waitFor(() => {
      expect(screen.getByText('42')).toBeInTheDocument();
      expect(screen.getByText('finance_user')).toBeInTheDocument();
      expect(screen.getByText('780 ms')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /Export CSV/i }));
    await waitFor(() => {
      expect(exportSpy).toHaveBeenCalledWith('csv', {
        search: undefined,
        event_type: undefined,
        outcome: undefined,
      });
    });

    getSpy.mockRestore();
    summarySpy.mockRestore();
    logsSpy.mockRestore();
    exportSpy.mockRestore();
  });

  it('displays explicit security verification pass and fail banners cleanly', () => {
    const { rerender } = render(<EvalSecurityTab rbacOverall="PASS" />);
    expect(screen.getByText('ReBAC & OWASP LLM Security Policy Verified')).toBeInTheDocument();

    rerender(<EvalSecurityTab rbacOverall="FAIL" />);
    expect(screen.getByText('Security / Authorization Breach Detected')).toBeInTheDocument();
  });
});
