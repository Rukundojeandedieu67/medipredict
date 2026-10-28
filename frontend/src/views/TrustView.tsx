import type { TrustMetrics, FeatureImportance } from "../types";
import { Icon } from "../components/Icons";
import { RiskBadge } from "../components/Badges";
import { EmptyState } from "../components/EmptyState";

interface TrustViewProps {
  metrics: TrustMetrics | null;
  loading: boolean;
}

function readableFeature(feature: string): string {
  return feature
    .replace(/^(numeric__|categorical__)/, "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function TrustView({ metrics, loading }: TrustViewProps) {
  const hasAccuracy = metrics?.accuracy !== null && metrics?.accuracy !== undefined && metrics.accuracy > 0;
  const features = (metrics?.feature_importances ?? []).slice(0, 10);
  const maxImportance = Math.max(...features.map((f) => f.importance), 0.001);

  return (
    <div className="trust-view-container">
      {/* Header */}
      <section className="section-header">
        <div>
          <div className="eyebrow-pill">
            <span className="eyebrow-dot" />
            METHODOLOGY &amp; MODEL GOVERNANCE
          </div>
          <h1 className="page-title">
            Model Governance &amp; Data Transparency<span className="heading-period">.</span>
          </h1>
          <p className="page-subtitle">
            Audit evaluation metrics, feature importances, and understand operational serving constraints.
          </p>
        </div>
        <div className="header-meta-badge">
          <Icon name="shield" size={14} />
          <span className="meta-label">Governed Model Inspection</span>
        </div>
      </section>

      {/* Critical Limitation Banner */}
      <div className="alert-notice-box">
        <div className="notice-icon-box">
          <Icon name="shield" size={20} />
        </div>
        <div className="notice-body">
          <h3>Operational Serving Policy: Rule-Based Fallback Logic</h3>
          <p>
            MediPredict Rwanda currently executes transparent <strong>rule-based days-of-cover logic</strong> for all live inventory classifications.
            Predictive machine-learning model serving is <strong>not enabled for live operational decisions</strong>.
            All historical metrics and test scores represent developmental baselines on demonstration tables and do not constitute evidence of real-world clinical performance.
          </p>
        </div>
      </div>

      {/* Grid: Metric Card + Feature Importances */}
      <div className="trust-layout-grid">
        {/* Left: Validation Accuracy Card */}
        <article className="panel accuracy-overview-card">
          <div className="panel-header">
            <div>
              <div className="panel-eyebrow">DEVELOPMENT BENCHMARK</div>
              <h2 className="panel-title">Model Accuracy</h2>
            </div>
            <span className="tag-neutral">Offline Test Split</span>
          </div>

          <div className="accuracy-metric-display">
            {hasAccuracy ? (
              <>
                <span className="big-acc-number">
                  {(metrics!.accuracy! * 100).toFixed(1)}
                  <small>%</small>
                </span>
                <span className="acc-caption">Validated test set accuracy</span>
              </>
            ) : (
              <>
                <span className="big-acc-number text-muted">—</span>
                <span className="acc-caption">Model serving disabled / withheld</span>
              </>
            )}
          </div>

          <div className="accuracy-details">
            <p>
              {hasAccuracy
                ? "Classification accuracy measured on held-out temporal evaluation slices during Phase 4 model training."
                : "No production model is currently authorized for live clinical serving. Procurement decisions must rely on source-maintained physical inventory records."}
            </p>
          </div>

          <div className="metric-source-box">
            <span className="source-label">Artifact Metadata Source:</span>
            <code className="source-path">
              {metrics?.source ? metrics.source.split(/[\\/]/).pop() : loading ? "Loading metadata…" : "medipredict_metrics.json"}
            </code>
          </div>
        </article>

        {/* Right: Feature Signals */}
        <article className="panel features-card">
          <div className="panel-header">
            <div>
              <div className="panel-eyebrow">PREDICTIVE SIGNALS</div>
              <h2 className="panel-title">Feature Importance Weights</h2>
            </div>
            <span className="tag-neutral">Top {features.length} Indicators</span>
          </div>

          {loading && !features.length ? (
            <div className="panel-loading">Loading model feature importance…</div>
          ) : features.length > 0 ? (
            <div className="feature-weight-list">
              {features.map((item: FeatureImportance, idx: number) => {
                const pct = (item.importance * 100).toFixed(1);
                const barWidth = Math.min(100, Math.max(2, (item.importance / maxImportance) * 100));

                return (
                  <div key={item.feature} className="feature-row-item">
                    <div className="feature-row-header">
                      <div className="feature-title-wrap">
                        <span className="feature-rank">#{idx + 1}</span>
                        <strong className="feature-name">{readableFeature(item.feature)}</strong>
                      </div>
                      <span className="feature-pct-val">{pct}%</span>
                    </div>
                    <div className="feature-bar-track">
                      <div className="feature-bar-fill" style={{ width: `${barWidth}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <EmptyState title="No Feature Data Available" icon="shield">
              No feature importance metrics are currently loaded in the repository artifacts store.
            </EmptyState>
          )}

          <div className="panel-footer-meta">
            <span>Features describe historical stockout correlations in synthetic reference datasets.</span>
          </div>
        </article>
      </div>

      {/* Class Level Precision and Recall */}
      {metrics && metrics.labels && metrics.labels.length > 0 && (
        <article className="panel class-level-metrics-panel">
          <div className="panel-header">
            <div>
              <div className="panel-eyebrow">CLASS PERFORMANCE</div>
              <h2 className="panel-title">Precision &amp; Recall by Risk Tier</h2>
              <p className="panel-description">
                Per-class performance breakdown evaluated against critical stockout labels.
              </p>
            </div>
          </div>

          <div className="class-grid-cards">
            {metrics.labels.map((label: string, index: number) => {
              const prec = metrics.precision[index];
              const rec = metrics.recall[index];

              return (
                <div key={label} className="class-perf-card">
                  <div className="class-perf-header">
                    <RiskBadge risk={label} />
                  </div>
                  <div className="class-perf-stats">
                    <div className="perf-metric">
                      <span className="perf-label">Precision</span>
                      <strong className="perf-val">
                        {prec !== undefined ? `${(prec * 100).toFixed(1)}%` : "—"}
                      </strong>
                    </div>
                    <div className="perf-metric">
                      <span className="perf-label">Recall</span>
                      <strong className="perf-val">
                        {rec !== undefined ? `${(rec * 100).toFixed(1)}%` : "—"}
                      </strong>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </article>
      )}

      {/* Governance & Provenance Statement */}
      <section className="panel governance-statement-panel">
        <div className="panel-header">
          <div>
            <div className="panel-eyebrow">DATA INTEGRITY AUDIT</div>
            <h3 className="panel-title">Provenance &amp; Validation Standards</h3>
          </div>
        </div>
        <div className="governance-body">
          <div className="governance-col">
            <h4>Synthetic Demonstration Data</h4>
            <p>
              Stock levels, consumption rates, and risk trajectories in demonstration datasets are synthetically generated.
              Every generated record carries <code>is_synthetic=true</code> in the API. No real patient or confidential hospital records are exposed.
            </p>
          </div>
          <div className="governance-col">
            <h4>District Indicators (NISR Context)</h4>
            <p>
              Under-5 population, poverty rates, and malaria prevalence are unverified seed values migrated from repository reference tables.
              They are provided for structural demonstration only and must not be cited as confirmed statistics.
            </p>
          </div>
          <div className="governance-col">
            <h4>No Random Time-Series Splits</h4>
            <p>
              Model training protocols require temporal out-of-time evaluation slices. Random train/test splits are strictly prohibited to prevent data leakage across inventory timelines.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
