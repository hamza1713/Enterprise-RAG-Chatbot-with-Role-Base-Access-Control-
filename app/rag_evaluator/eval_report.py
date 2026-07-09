"""
app/rag_evaluator/eval_report.py
──────────────────────────────────
Generates a rich HTML evaluation report combining:
  - RAGAS quality metrics (per-role and overall)
  - RBAC security test results
  - Historical trend tracking (if previous results exist)

Output: ragas_report.html — can be opened in any browser.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("FinSight.EvalReport")

REPORT_DIR = Path(__file__).parent


# ══════════════════════════════════════════════════════════════════════════════
#  COLOUR HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _score_to_color(score: float, thresholds: dict) -> str:
    """Return a CSS colour class based on score vs thresholds."""
    if score >= thresholds.get("warn", 0.75):
        return "score-pass"
    elif score >= thresholds.get("pass", 0.65):
        return "score-warn"
    else:
        return "score-fail"


def _status_badge(status: str) -> str:
    cls = {"PASS": "badge-pass", "WARN": "badge-warn", "FAIL": "badge-fail"}.get(status, "badge-info")
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(status, "ℹ️")
    return f'<span class="badge {cls}">{icon} {status}</span>'


# ══════════════════════════════════════════════════════════════════════════════
#  RADAR CHART DATA (inline Chart.js)
# ══════════════════════════════════════════════════════════════════════════════

def _build_radar_datasets(per_role: dict[str, dict]) -> str:
    """Build Chart.js datasets JSON for the radar chart."""
    metric_labels = [
        "Faithfulness", "Answer Relevancy",
        "Context Precision", "Context Recall", "Answer Correctness"
    ]
    metric_keys = [
        "faithfulness", "answer_relevancy",
        "context_precision", "context_recall", "answer_correctness"
    ]
    palette = [
        "rgba(99,102,241,0.7)",   # indigo
        "rgba(16,185,129,0.7)",   # emerald
        "rgba(245,158,11,0.7)",   # amber
        "rgba(239,68,68,0.7)",    # red
        "rgba(59,130,246,0.7)",   # blue
        "rgba(168,85,247,0.7)",   # purple
    ]
    datasets = []
    for i, (role, scores) in enumerate(sorted(per_role.items())):
        color = palette[i % len(palette)]
        data  = [scores.get(k, 0.0) for k in metric_keys]
        datasets.append({
            "label":            role.title(),
            "data":             data,
            "backgroundColor":  color.replace("0.7", "0.2"),
            "borderColor":      color,
            "borderWidth":      2,
            "pointBackgroundColor": color,
        })
    return json.dumps({
        "labels":   metric_labels,
        "datasets": datasets,
    })


# ══════════════════════════════════════════════════════════════════════════════
#  HTML GENERATION
# ══════════════════════════════════════════════════════════════════════════════

CSS = """
:root {
  --bg:        #0f172a;
  --surface:   #1e293b;
  --surface2:  #273344;
  --border:    #334155;
  --text:      #e2e8f0;
  --text-dim:  #94a3b8;
  --pass:      #10b981;
  --warn:      #f59e0b;
  --fail:      #ef4444;
  --indigo:    #6366f1;
  --radius:    12px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  padding: 2rem;
}
h1 { font-size: 2rem; font-weight: 800; color: #fff; letter-spacing: -0.5px; }
h2 { font-size: 1.25rem; font-weight: 700; color: var(--indigo); margin-bottom: 1rem; }
h3 { font-size: 1rem; font-weight: 600; color: var(--text-dim); margin-bottom: 0.5rem; }
.header {
  display: flex; align-items: center; gap: 1rem;
  margin-bottom: 2.5rem; padding-bottom: 1.5rem;
  border-bottom: 1px solid var(--border);
}
.header-logo {
  width: 48px; height: 48px; border-radius: 12px;
  background: linear-gradient(135deg, var(--indigo), #818cf8);
  display: flex; align-items: center; justify-content: center;
  font-size: 1.5rem;
}
.meta { color: var(--text-dim); font-size: 0.85rem; margin-top: 0.25rem; }
.overall-badge {
  margin-left: auto;
  padding: 0.75rem 2rem;
  border-radius: 50px;
  font-weight: 800;
  font-size: 1.1rem;
  letter-spacing: 1px;
}
.overall-pass { background: rgba(16,185,129,0.15); color: var(--pass); border: 2px solid var(--pass); }
.overall-fail { background: rgba(239,68,68,0.15);  color: var(--fail); border: 2px solid var(--fail); }
.overall-warn { background: rgba(245,158,11,0.15); color: var(--warn); border: 2px solid var(--warn); }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }
.grid-3 { display: grid; grid-template-columns: repeat(3,1fr); gap: 1rem; margin-bottom: 2rem; }
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.5rem;
}
.stat-card { text-align: center; }
.stat-value { font-size: 2.5rem; font-weight: 800; line-height: 1; }
.stat-label { font-size: 0.8rem; color: var(--text-dim); margin-top: 0.35rem; text-transform: uppercase; letter-spacing: 1px; }
.badge {
  display: inline-block;
  padding: 0.25rem 0.75rem;
  border-radius: 50px;
  font-size: 0.8rem;
  font-weight: 700;
}
.badge-pass { background: rgba(16,185,129,0.15); color: var(--pass); }
.badge-warn { background: rgba(245,158,11,0.15);  color: var(--warn); }
.badge-fail { background: rgba(239,68,68,0.15);   color: var(--fail); }
.score-pass { color: var(--pass); font-weight: 700; }
.score-warn { color: var(--warn); font-weight: 700; }
.score-fail { color: var(--fail); font-weight: 700; }
table {
  width: 100%; border-collapse: collapse;
  font-size: 0.88rem;
}
thead th {
  background: var(--surface2);
  padding: 0.75rem 1rem;
  text-align: left;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-dim);
  border-bottom: 1px solid var(--border);
}
tbody td {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
}
tbody tr:hover { background: var(--surface2); }
.progress-bar {
  display: flex; align-items: center; gap: 0.75rem;
}
.bar-track {
  flex: 1; height: 8px; background: var(--border); border-radius: 4px; overflow: hidden;
}
.bar-fill {
  height: 100%; border-radius: 4px;
  transition: width 0.3s ease;
}
.bar-pass { background: var(--pass); }
.bar-warn { background: var(--warn); }
.bar-fail { background: var(--fail); }
.bar-val  { font-size: 0.8rem; font-weight: 700; min-width: 45px; text-align: right; }
.chart-container { height: 350px; position: relative; }
section { margin-bottom: 2rem; }
.threshold-note {
  font-size: 0.78rem; color: var(--text-dim);
  margin-top: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: rgba(99,102,241,0.08);
  border-left: 3px solid var(--indigo);
  border-radius: 0 4px 4px 0;
}
.security-test-row td:first-child { font-family: monospace; font-size: 0.82rem; }
"""

def _make_bar(score: float, css_class: str) -> str:
    pct = int(score * 100)
    bar_cls = f"bar-{'pass' if css_class == 'score-pass' else 'warn' if css_class == 'score-warn' else 'fail'}"
    return (
        f'<div class="progress-bar">'
        f'<div class="bar-track"><div class="bar-fill {bar_cls}" style="width:{pct}%"></div></div>'
        f'<span class="bar-val {css_class}">{score:.3f}</span>'
        f'</div>'
    )


def _overall_metrics_table(overall: dict, pass_fail: dict) -> str:
    from app.rag_evaluator.ragas_evaluator import THRESHOLDS

    rows = ""
    for metric, score in overall.items():
        status    = pass_fail.get(metric, "PASS")
        t         = THRESHOLDS.get(metric, {"pass": 0.65, "warn": 0.75})
        css_cls   = _score_to_color(score, t)
        bar_html  = _make_bar(score, css_cls)
        rows += (
            f"<tr><td>{metric.replace('_',' ').title()}</td>"
            f"<td>{bar_html}</td>"
            f"<td>{t['pass']:.2f}</td>"
            f"<td>{t['warn']:.2f}</td>"
            f"<td>{_status_badge(status)}</td></tr>"
        )
    return f"""
    <table>
      <thead><tr>
        <th>Metric</th><th>Score</th><th>Min Threshold</th>
        <th>Target</th><th>Status</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <p class="threshold-note">
      Min Threshold = CI/CD gate (FAIL below this) |
      Target = optimal production value (WARN between min and target)
    </p>
    """


def _per_role_table(per_role: dict) -> str:
    if not per_role:
        return "<p style='color:var(--text-dim)'>No per-role data available.</p>"

    all_metrics = list(next(iter(per_role.values())).keys())
    header = "".join(f"<th>{m.replace('_',' ').title()}</th>" for m in all_metrics)
    rows   = ""
    for role, scores in sorted(per_role.items()):
        cells = ""
        for m in all_metrics:
            s = scores.get(m, 0.0)
            from app.rag_evaluator.ragas_evaluator import THRESHOLDS
            t   = THRESHOLDS.get(m, {"pass": 0.65, "warn": 0.75})
            cls = _score_to_color(s, t)
            cells += f"<td class='{cls}'>{s:.4f}</td>"
        rows += f"<tr><td><strong>{role.title()}</strong></td>{cells}</tr>"

    return f"""
    <table>
      <thead><tr><th>Role</th>{header}</tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def _security_tests_table(tests: list[dict]) -> str:
    rows = ""
    for t in tests:
        status = t.get("status", "WARN")
        score  = t.get("score", 0.0)
        bar_cls = "score-" + status.lower()
        bar_html = _make_bar(score, bar_cls)
        rows += (
            f'<tr class="security-test-row">'
            f"<td>{t['test']}</td>"
            f"<td>{bar_html}</td>"
            f"<td>{_status_badge(status)}</td>"
            f"<td style='font-size:0.8rem;color:var(--text-dim)'>{t.get('details','')[:120]}…</td>"
            f"</tr>"
        )
    return f"""
    <table>
      <thead><tr>
        <th>Test</th><th>Security Score</th><th>Status</th><th>Details</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def generate_html_report(
    ragas_results: Optional[dict] = None,
    security_report: Optional[dict] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    Generate a full HTML evaluation report.

    Args:
        ragas_results:    Output from ragas_evaluator.run_ragas_evaluation()
        security_report:  Output from rbac_security_eval.run_all_security_tests()
        output_path:      Where to save the HTML file. Defaults to ragas_report.html

    Returns:
        Path to the generated HTML file.
    """
    if output_path is None:
        output_path = str(REPORT_DIR / "ragas_report.html")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Derive overall status ─────────────────────────────────────────────────
    ragas_ok  = ragas_results and all(v != "FAIL" for v in ragas_results.get("pass_fail", {}).values())
    rbac_ok   = security_report and security_report.get("overall_status") == "PASS"

    if ragas_results and security_report:
        overall_status = "PASS" if (ragas_ok and rbac_ok) else ("WARN" if (ragas_ok or rbac_ok) else "FAIL")
    elif ragas_results:
        overall_status = "PASS" if ragas_ok else "FAIL"
    elif security_report:
        overall_status = "PASS" if rbac_ok else "FAIL"
    else:
        overall_status = "WARN"

    badge_cls = {"PASS": "overall-pass", "WARN": "overall-warn", "FAIL": "overall-fail"}[overall_status]
    badge_icon = {"PASS": "✅ PASS", "WARN": "⚠️ WARN", "FAIL": "❌ FAIL"}[overall_status]

    # ── Summary stats ──────────────────────────────────────────────────────────
    ragas_overall   = ragas_results.get("overall", {}) if ragas_results else {}
    ragas_per_role  = ragas_results.get("per_role", {}) if ragas_results else {}
    ragas_pass_fail = ragas_results.get("pass_fail", {}) if ragas_results else {}
    security_tests  = security_report.get("tests", []) if security_report else []
    security_summary= security_report.get("summary", {}) if security_report else {}

    avg_ragas = (
        round(sum(ragas_overall.values()) / max(len(ragas_overall), 1), 3)
        if ragas_overall else 0.0
    )
    sec_score = security_summary.get("avg_score", 0.0)

    # ── Stat cards ─────────────────────────────────────────────────────────────
    stat_cards = f"""
    <div class="grid-3">
      <div class="card stat-card">
        <div class="stat-value score-{'pass' if avg_ragas >= 0.70 else 'warn' if avg_ragas >= 0.55 else 'fail'}">{avg_ragas:.3f}</div>
        <div class="stat-label">Avg RAGAS Score</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value score-{'pass' if sec_score >= 0.80 else 'warn' if sec_score >= 0.60 else 'fail'}">{sec_score:.3f}</div>
        <div class="stat-label">RBAC Security Score</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value">{len(ragas_per_role)}</div>
        <div class="stat-label">Roles Evaluated</div>
      </div>
    </div>
    """

    # ── RAGAS section ──────────────────────────────────────────────────────────
    ragas_section = ""
    if ragas_results:
        radar_data    = _build_radar_datasets(ragas_per_role) if ragas_per_role else "null"
        ragas_section = f"""
        <section>
          <h2>📊 RAGAS Quality Metrics</h2>
          <div class="grid-2">
            <div class="card">
              <h3>Overall Metric Scores</h3>
              {_overall_metrics_table(ragas_overall, ragas_pass_fail)}
            </div>
            <div class="card">
              <h3>Per-Role Radar Chart</h3>
              <div class="chart-container">
                <canvas id="radarChart"></canvas>
              </div>
            </div>
          </div>

          <div class="card">
            <h3>Per-Role Score Breakdown</h3>
            {_per_role_table(ragas_per_role)}
          </div>
        </section>
        """
    else:
        ragas_section = "<section><div class='card'><p style='color:var(--text-dim)'>No RAGAS quality evaluation data available.</p></div></section>"

    # ── RBAC section ───────────────────────────────────────────────────────────
    security_section = ""
    if security_tests:
        passed = security_summary.get("passed", 0)
        warned = security_summary.get("warned", 0)
        failed = security_summary.get("failed", 0)
        total  = security_summary.get("total_tests", 0)
        security_section = f"""
        <section>
          <h2>🔐 RBAC Authorization Security Tests</h2>
          <div class="grid-3" style="margin-bottom:1.5rem">
            <div class="card stat-card">
              <div class="stat-value score-pass">{passed}</div>
              <div class="stat-label">Tests Passed</div>
            </div>
            <div class="card stat-card">
              <div class="stat-value score-warn">{warned}</div>
              <div class="stat-label">Warnings</div>
            </div>
            <div class="card stat-card">
              <div class="stat-value score-fail">{failed}</div>
              <div class="stat-label">Tests Failed</div>
            </div>
          </div>
          <div class="card">
            <h3>Security Test Results ({total} tests)</h3>
            {_security_tests_table(security_tests)}
          </div>
        </section>
        """
    else:
        security_section = "<section><div class='card'><p style='color:var(--text-dim)'>No RBAC security evaluation data available.</p></div></section>"

    # ── Radar chart JS ─────────────────────────────────────────────────────────
    radar_js = ""
    if ragas_per_role:
        radar_data = _build_radar_datasets(ragas_per_role)
        radar_js   = f"""
        <script>
        (function() {{
          const ctx = document.getElementById('radarChart');
          if (!ctx) return;
          new Chart(ctx, {{
            type: 'radar',
            data: {radar_data},
            options: {{
              responsive: true,
              maintainAspectRatio: false,
              plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }},
              scales: {{
                r: {{
                  min: 0, max: 1,
                  ticks: {{ color: '#94a3b8', backdropColor: 'transparent', stepSize: 0.2 }},
                  grid: {{ color: 'rgba(148,163,184,0.2)' }},
                  pointLabels: {{ color: '#e2e8f0', font: {{ size: 11 }} }}
                }}
              }}
            }}
          }});
        }})();
        </script>
        """

    # ── Full HTML ──────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>FinSight — RAGAS Evaluation Report</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>{CSS}</style>
</head>
<body>
  <div class="header">
    <div class="header-logo">🔎</div>
    <div>
      <h1>FinSight Evaluation Report</h1>
      <div class="meta">RAGAS + RBAC Security Evaluation &nbsp;|&nbsp; {now_str}</div>
    </div>
    <div class="overall-badge {badge_cls}">{badge_icon}</div>
  </div>

  {stat_cards}
  {ragas_section}
  {security_section}

  <footer style="color:var(--text-dim);font-size:0.78rem;text-align:center;margin-top:3rem;">
    Generated by FinSight RAGAS Evaluation Framework &nbsp;·&nbsp; {now_str}
  </footer>

  {radar_js}
</body>
</html>
"""

    Path(output_path).write_text(html, encoding="utf-8")
    logger.info(f"[Report] HTML report saved to {output_path}")
    return output_path


def load_and_generate_report(
    ragas_csv: Optional[str] = None,
    security_json: Optional[str] = None,
    output_html: Optional[str] = None,
) -> str:
    """
    Load existing result files and regenerate the HTML report.
    Useful for regenerating after manual review of CSV results.
    """
    ragas_results   = None
    security_report = None

    if ragas_csv and Path(ragas_csv).exists():
        df = pd.read_csv(ragas_csv)
        metric_cols = [c for c in df.columns if c in {
            "faithfulness", "answer_relevancy", "context_precision",
            "context_recall", "answer_correctness"
        }]
        overall = {c: round(float(df[c].mean(skipna=True)), 4) for c in metric_cols}

        from app.rag_evaluator.ragas_evaluator import _apply_thresholds
        per_role = {}
        if "role" in df.columns:
            for role, grp in df.groupby("role"):
                per_role[str(role)] = {c: round(float(grp[c].mean(skipna=True)), 4) for c in metric_cols}

        ragas_results = {
            "overall":   overall,
            "per_role":  per_role,
            "pass_fail": _apply_thresholds(overall),
            "csv_path":  ragas_csv,
        }

    if security_json and Path(security_json).exists():
        with open(security_json, encoding="utf-8") as f:
            security_report = json.load(f)

    return generate_html_report(
        ragas_results=ragas_results,
        security_report=security_report,
        output_path=output_html,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ragas_csv   = str(REPORT_DIR / "evaluation_results_ragas.csv")
    sec_json    = str(REPORT_DIR / "rbac_security_report.json")
    out         = load_and_generate_report(ragas_csv, sec_json)
    print(f"Report: {out}")
