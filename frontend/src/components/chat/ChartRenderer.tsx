import { useState } from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import type { ChartSpec } from '../../types';
import { Code2, BarChart2 } from 'lucide-react';

const CHART_COLORS = ['#7edbc2', '#60a5fa', '#a78bfa', '#f59e0b'];

interface ChartRendererProps {
  chartSpec?: ChartSpec | null;
  sql?: string | null;
}

export default function ChartRenderer({ chartSpec, sql }: ChartRendererProps) {
  const [showSql, setShowSql] = useState(false);

  const hasChart = Boolean(
    chartSpec &&
      chartSpec.type !== 'none' &&
      chartSpec.rows &&
      chartSpec.rows.length > 0 &&
      chartSpec.yKeys.length > 0
  );

  if (!hasChart && !sql) return null;

  return (
    <div className="sql-artifact-box">
      <div className="sql-artifact-header">
        <span className="sql-artifact-title">
          <BarChart2 size={14} />
          <span>{hasChart ? chartSpec!.title || 'Analytics Chart' : 'DuckDB SQL'}</span>
        </span>
        {sql && (
          <button
            type="button"
            className="fs-btn fs-btn-secondary sql-toggle-btn"
            onClick={() => setShowSql((v) => !v)}
          >
            <Code2 size={13} />
            <span>{showSql ? 'Hide SQL' : 'View SQL'}</span>
          </button>
        )}
      </div>

      {showSql && sql && (
        <pre className="sql-code-block">
          <code>{sql}</code>
        </pre>
      )}

      {hasChart && chartSpec && (
        <div className="sql-chart-canvas">
          <ResponsiveContainer width="100%" height={250}>
            {chartSpec.type === 'line' ? (
              <LineChart data={chartSpec.rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a373b" />
                <XAxis dataKey={chartSpec.xKey} stroke="#94a7a3" fontSize={11} />
                <YAxis stroke="#94a7a3" fontSize={11} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: '11px' }} />
                {chartSpec.yKeys.map((yk, idx) => (
                  <Line
                    key={yk}
                    type="monotone"
                    dataKey={yk}
                    stroke={CHART_COLORS[idx % CHART_COLORS.length]}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                ))}
              </LineChart>
            ) : chartSpec.type === 'area' ? (
              <AreaChart data={chartSpec.rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a373b" />
                <XAxis dataKey={chartSpec.xKey} stroke="#94a7a3" fontSize={11} />
                <YAxis stroke="#94a7a3" fontSize={11} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: '11px' }} />
                {chartSpec.yKeys.map((yk, idx) => (
                  <Area
                    key={yk}
                    type="monotone"
                    dataKey={yk}
                    stroke={CHART_COLORS[idx % CHART_COLORS.length]}
                    fill={CHART_COLORS[idx % CHART_COLORS.length]}
                    fillOpacity={0.22}
                  />
                ))}
              </AreaChart>
            ) : chartSpec.type === 'pie' ? (
              <PieChart>
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: '11px' }} />
                <Pie
                  data={chartSpec.rows}
                  dataKey={chartSpec.yKeys[0]}
                  nameKey={chartSpec.xKey}
                  cx="50%"
                  cy="50%"
                  outerRadius={88}
                  label
                >
                  {chartSpec.rows.map((_entry, idx) => (
                    <Cell key={idx} fill={CHART_COLORS[idx % CHART_COLORS.length]} />
                  ))}
                </Pie>
              </PieChart>
            ) : (
              <BarChart data={chartSpec.rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a373b" />
                <XAxis dataKey={chartSpec.xKey} stroke="#94a7a3" fontSize={11} />
                <YAxis stroke="#94a7a3" fontSize={11} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: '11px' }} />
                {chartSpec.yKeys.map((yk, idx) => (
                  <Bar
                    key={yk}
                    dataKey={yk}
                    fill={CHART_COLORS[idx % CHART_COLORS.length]}
                    radius={[4, 4, 0, 0]}
                  />
                ))}
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

const tooltipStyle = {
  backgroundColor: '#121b1e',
  border: '1px solid #2a373b',
  borderRadius: '8px',
  color: '#f1f5f4',
  fontSize: '12px',
};
