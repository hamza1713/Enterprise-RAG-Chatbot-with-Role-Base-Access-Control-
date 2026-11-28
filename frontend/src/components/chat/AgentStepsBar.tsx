import { useState } from 'react';
import type { AgentStep } from '../../types';
import { CheckCircle2, AlertTriangle, Loader2, ChevronDown, ChevronUp, Cpu } from 'lucide-react';

interface AgentStepsBarProps {
  steps: AgentStep[];
  isStreaming?: boolean;
}

export default function AgentStepsBar({ steps, isStreaming = false }: AgentStepsBarProps) {
  const [expanded, setExpanded] = useState(isStreaming);
  if (!steps || steps.length === 0) return null;

  const latest = steps[steps.length - 1];

  return (
    <div className="agent-steps-box">
      <button
        type="button"
        className="agent-steps-toggle"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <Cpu size={13} />
        <span>
          {isStreaming
            ? latest.label || 'Running agent workflow…'
            : `Agent workflow (${steps.length} steps)`}
        </span>
        {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>

      {expanded && (
        <ul className="agent-steps-list">
          {steps.map((step, idx) => (
            <li key={`${step.node}-${idx}`} className="agent-step-row">
              {step.status === 'running' ? (
                <Loader2 size={13} className="spin" color="#7edbc2" />
              ) : step.status === 'error' ? (
                <AlertTriangle size={13} color="#fca5a5" />
              ) : (
                <CheckCircle2 size={13} color="#7edbc2" />
              )}
              <div>
                <strong>{step.label}</strong>
                {step.detail && <small>{step.detail}</small>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
