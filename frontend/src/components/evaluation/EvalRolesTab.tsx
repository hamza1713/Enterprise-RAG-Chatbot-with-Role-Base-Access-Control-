import {
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
} from 'recharts';
import type { RagasScores } from '../../types';
import {
  METRIC_KEYS,
  ROLE_COLORS,
  checkMetricStatus,
  getMetricBgClass,
  getMetricColor,
} from './evalHelpers';

interface EvalRolesTabProps {
  perRoleScores: Record<string, RagasScores>;
}

const GLOSSARY = [
  { name: 'Faithfulness', color: '#509f81', desc: 'Is the answer grounded strictly in the retrieved context?' },
  { name: 'Answer Relevancy', color: '#8B5CF6', desc: 'Does the answer address the user question directly?' },
  { name: 'Context Precision', color: '#3B82F6', desc: 'Are retrieved chunks ranked cleanly by relevance?' },
  { name: 'Context Recall', color: '#10B981', desc: 'Does retrieved context cover the facts in the ground truth?' },
  { name: 'Answer Correctness', color: '#EC4899', desc: 'Factual & semantic alignment against reference ground truth.' },
];

export default function EvalRolesTab({ perRoleScores }: EvalRolesTabProps) {
  const rolesPresent = Object.keys(perRoleScores);
  const radarData = [
    { key: 'faithfulness', name: 'Faithfulness' },
    { key: 'answer_relevancy', name: 'Answer Relevancy' },
    { key: 'context_precision', name: 'Context Precision' },
    { key: 'context_recall', name: 'Context Recall' },
    { key: 'answer_correctness', name: 'Answer Correctness' },
  ].map((m) => {
    const item: Record<string, string | number> = { subject: m.name };
    Object.entries(perRoleScores).forEach(([role, scores]) => {
      const val = scores[m.key];
      item[role] = val ? Math.round(val * 100) : 0;
    });
    return item;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div className="eval-results-flex">
        <div className="fs-card" style={{ flex: 1, padding: '24px' }}>
          <h3 style={{ fontSize: '14.5px', fontWeight: 700, marginBottom: '20px' }}>Per-Role Metrics Overlay</h3>
          <div style={{ width: '100%', height: '360px' }}>
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart cx="50%" cy="50%" outerRadius="75%" data={radarData}>
                <PolarGrid stroke="rgba(94,157,128, 0.15)" />
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
                  contentStyle={{ background: '#0f171a', border: '1px solid var(--border)', borderRadius: '6px' }}
                  labelStyle={{ color: '#fff', fontWeight: 'bold' }}
                  formatter={(value, name) => [`${value}%`, name]}
                />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="fs-card" style={{ width: '360px', maxWidth: '100%', padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h3 style={{ fontSize: '14.5px', fontWeight: 700, margin: 0 }}>Quality Metrics Glossary</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', maxHeight: '360px' }}>
            {GLOSSARY.map((item) => (
              <div key={item.name} className="eval-glossary-item">
                <strong style={{ color: item.color }}>{item.name}:</strong>
                <p style={{ margin: '2px 0 0 0', fontSize: '11.5px', color: 'var(--text-secondary)' }}>{item.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="fs-card" style={{ padding: '24px' }}>
        <h3 style={{ fontSize: '14.5px', fontWeight: 700, marginBottom: '16px' }}>Department-wise Performance Matrix</h3>
        <div className="fs-table-wrap" style={{ marginTop: 0 }}>
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
              {Object.entries(perRoleScores).map(([role, scores]) => (
                <tr key={role}>
                  <td style={{ fontWeight: 'bold' }}>
                    <span
                      style={{
                        display: 'inline-block',
                        width: '8px',
                        height: '8px',
                        borderRadius: '50%',
                        background: ROLE_COLORS[role.toLowerCase()] || '#64748B',
                        marginRight: '8px',
                      }}
                    />
                    {role.toUpperCase()}
                  </td>
                  {METRIC_KEYS.map((metric) => {
                    const score = scores[metric];
                    if (score === undefined || score === null) {
                      return (
                        <td key={metric} style={{ color: 'var(--text-muted)', textAlign: 'center' }}>
                          —
                        </td>
                      );
                    }
                    const status = checkMetricStatus(metric, score);
                    return (
                      <td
                        key={metric}
                        style={{
                          color: getMetricColor(status),
                          background: getMetricBgClass(status),
                          fontWeight: 600,
                          fontFamily: 'var(--font-mono)',
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
  );
}
