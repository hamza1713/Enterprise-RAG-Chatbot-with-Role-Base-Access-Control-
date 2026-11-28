import { CheckCircle, ShieldAlert, ShieldCheck } from 'lucide-react';

interface EvalSecurityTabProps {
  rbacOverall?: string;
}

const CHECKLIST = [
  {
    title: 'Unauthorized Cross-Department Blocking',
    desc: 'Verifies isolated department roles cannot retrieve confidential documents or datasets from peer departments.',
  },
  {
    title: 'Authorized ReBAC Access Allowance',
    desc: 'Ensures ReBAC-authorized documents and shared file tuples are retrieved accurately for legitimate requests.',
  },
  {
    title: 'C-Level Executive Visibility',
    desc: 'Confirms executive governance accounts retain cross-departmental RAG and Parquet analytics inspection scope.',
  },
  {
    title: 'OWASP LLM01 Indirect & Direct Injection Guardrails',
    desc: 'Quarantines instruction-override, chat-template smuggling, and hidden comment/image exfiltration vectors.',
  },
  {
    title: 'OWASP LLM02 PII & Credential Redaction + PostgreSQL/OpenFGA Enforcements',
    desc: 'Pre-filters PostgreSQL pgvector HNSW/BM25 retrieval with OpenFGA doc IDs and redacts keys, JWTs, SSNs, and cards on output.',
  },
];

export default function EvalSecurityTab({ rbacOverall }: EvalSecurityTabProps) {
  const passed = ['PASS', 'PASSED'].includes((rbacOverall || '').toUpperCase());

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div className="fs-card" style={{ padding: '24px' }}>
        <div className={passed ? 'eval-security-pass' : 'eval-security-fail'}>
          {passed ? <ShieldCheck size={36} color="#34D399" /> : <ShieldAlert size={36} color="#F87171" />}
          <div>
            <div style={{ fontWeight: 'bold', fontSize: '16px', color: '#fff' }}>
              {passed
                ? 'ReBAC & OWASP LLM Security Policy Verified'
                : 'Security / Authorization Breach Detected'}
            </div>
            <div style={{ fontSize: '13px', color: passed ? '#CBD5E1' : '#FCA5A5', marginTop: '4px' }}>
              {passed
                ? 'All automated ReBAC access control and OWASP LLM01/LLM02 guardrail verification checks passed.'
                : 'One or more security verification checks failed or have not yet passed cleanly.'}
            </div>
          </div>
        </div>
      </div>

      <div className="fs-card" style={{ padding: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
          <ShieldCheck size={20} color="var(--primary)" />
          <h3 style={{ fontSize: '14.5px', fontWeight: 700, margin: 0 }}>Security & Guardrail Checklist</h3>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {CHECKLIST.map((item) => (
            <div key={item.title} className="eval-glossary-item" style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
              <CheckCircle size={16} color="#34D399" style={{ marginTop: '2px', flexShrink: 0 }} />
              <div>
                <strong style={{ fontSize: '13px' }}>{item.title}</strong>
                <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>{item.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
