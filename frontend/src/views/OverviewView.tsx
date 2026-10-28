import { useMemo } from "react";
import type { RiskRecord, Summary, TransferCandidate, StockAlert } from "../types";
import { Icon } from "../components/Icons";
import { StatCard } from "../components/StatCard";
import { CoverBadge, ProvenanceBadge } from "../components/Badges";
import { EmptyState } from "../components/EmptyState";

interface OverviewViewProps {
  summary: Summary | null;
  risks: RiskRecord[];
  alerts: StockAlert[];
  transfers: TransferCandidate[];
  loading: boolean;
  onNavigate: (view: string) => void;
  onInspectMedicine: (medicine: RiskRecord) => void;
  alertStatuses: Record<string, "open" | "acknowledged" | "resolved">;
}

function formatNum(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat().format(value);
}

export function OverviewView({
  summary,
  risks,
  alerts,
  transfers,
  loading,
  onNavigate,
  onInspectMedicine,
  alertStatuses,
}: OverviewViewProps) {
  // Compute prioritized critical issues sorted by operational severity
  const priorityIssues = useMemo(() => {
    return [...risks]
      .filter((r) => r.risk_level.toLowerCase() === "critical" || r.stock_units <= 0)
      .sort((a, b) => {
        // Zero stock first
        if (a.stock_units <= 0 && b.stock_units > 0) return -1;
        if (b.stock_units <= 0 && a.stock_units > 0) return 1;
        // Then lowest days of cover
        const coverA = a.lead_time_days ?? 0;
        const coverB = b.lead_time_days ?? 0;
        return coverA - coverB;
      })
      .slice(0, 6);
  }, [risks]);

  // Alert unresolved status count
  const openAlertsCount = useMemo(() => {
    return alerts.filter((a) => {
      const status = alertStatuses[a.alert_id] || "open";
      return status !== "resolved";
    }).length;
  }, [alerts, alertStatuses]);

  // Risk health counts
  const totalRecords =
    (summary?.critical ?? 0) +
    (summary?.moderate ?? 0) +
    (summary?.stable ?? 0) +
    (summary?.unknown ?? 0);

  const criticalPct = totalRecords ? Math.round(((summary?.critical ?? 0) / totalRecords) * 100) : 0;
  const moderatePct = totalRecords ? Math.round(((summary?.moderate ?? 0) / totalRecords) * 100) : 0;
  const stablePct = totalRecords ? Math.round(((summary?.stable ?? 0) / totalRecords) * 100) : 0;
  const unknownPct = totalRecords ? Math.round(((summary?.unknown ?? 0) / totalRecords) * 100) : 0;

  // Province distribution summary from real loaded rows
  const provinceSummary = useMemo(() => {
    const map = new Map<string, { total: number; critical: number }>();
    for (const r of risks) {
      const p = r.province || "Other";
      const existing = map.get(p) || { total: 0, critical: 0 };
      existing.total += 1;
      if (r.risk_level.toLowerCase() === "critical") {
        existing.critical += 1;
      }
      map.set(p, existing);
    }
    return Array.from(map.entries()).sort((a, b) => b[1].critical - a[1].critical);
  }, [risks]);

  return (
    <div className="overview-container">
      {/* Top Welcome & Actions Header */}
      <section className="overview-hero">
        <div className="overview-hero-left">
          <div className="eyebrow-pill">
            <span className="eyebrow-dot" />
            MEDICINE AVAILABILITY MONITORING
          </div>
          <h1 className="hero-title">
            Supply Chain Situation Overview<span className="heading-period">.</span>
          </h1>
          <p className="hero-subtitle">
            Continuous operational visibility across health facilities and medicines in Rwanda.
          </p>
        </div>
        <div className="hero-actions">
          <button
            type="button"
            className="secondary-action-button"
            onClick={() => onNavigate("inventory")}
          >
            <Icon name="package" size={16} />
            Browse Inventory
          </button>
          <button
            type="button"
            className="primary-action-button"
            onClick={() => onNavigate("upload")}
          >
            <Icon name="upload" size={16} />
            Assess Inventory CSV
          </button>
        </div>
      </section>

      {/* KPI Stat Cards */}
      <section className="stat-cards-grid">
        <StatCard
          label="Monitored Facilities"
          value={summary ? formatNum(summary.facilities) : loading ? "—" : "Unavailable"}
          note={`${summary ? formatNum(summary.districts) : "—"} administrative districts`}
          icon="building"
          tone="mint"
          tooltip="Total distinct health facilities reporting monthly inventory in the current operational dataset."
          onClick={() => onNavigate("inventory")}
        />
        <StatCard
          label="Open / Unresolved Alerts"
          value={loading ? "—" : formatNum(openAlertsCount)}
          note={`${formatNum(summary?.critical)} critical · ${formatNum(summary?.moderate)} moderate`}
          icon="alert-triangle"
          tone="rose"
          tooltip="Active alerts requiring attention. Click to review in the Stock Alerts view."
          badge={
            openAlertsCount > 0 ? (
              <span className="stat-alert-tag">{openAlertsCount} action needed</span>
            ) : undefined
          }
          onClick={() => onNavigate("alerts")}
        />
        <StatCard
          label="Medicines Tracked"
          value={summary ? formatNum(summary.medicines) : loading ? "—" : "Unavailable"}
          note={`${summary ? formatNum(summary.stock_units) : "—"} total units on hand`}
          icon="package"
          tone="blue"
          tooltip="Distinct essential medicine products monitored across all reporting facilities."
          onClick={() => onNavigate("inventory")}
        />
        <StatCard
          label="Rebalancing Transfers"
          value={formatNum(transfers.length)}
          note="Candidate surplus-to-deficit routes"
          icon="truck"
          tone="amber"
          tooltip="Suggested stock transfers from donor facilities (>30 days cover) to deficit facilities (<14 days cover)."
          onClick={() => onNavigate("transfers")}
        />
      </section>

      {/* Middle Layout: Priority Issues + Stock Health Distribution */}
      <section className="overview-split-layout">
        {/* Left: Prioritized Action Items */}
        <article className="panel priority-panel">
          <div className="panel-header">
            <div>
              <div className="panel-eyebrow">URGENT ACTION REQUIRED</div>
              <h2 className="panel-title">Medicines Requiring Attention First</h2>
              <p className="panel-description">
                Stockouts and facilities with critical buffer depletion (under 7 days of cover remaining).
              </p>
            </div>
            <button
              type="button"
              className="panel-link-btn"
              onClick={() => onNavigate("alerts")}
            >
              <span>View All Alerts</span>
              <Icon name="arrow-right" size={14} />
            </button>
          </div>

          {loading && !risks.length ? (
            <div className="panel-loading">Loading priority records…</div>
          ) : priorityIssues.length > 0 ? (
            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Facility &amp; District</th>
                    <th>Medicine</th>
                    <th>Stock on Hand</th>
                    <th>Days of Cover</th>
                    <th>Recommended Next Step</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {priorityIssues.map((item, index) => {
                    const isZero = item.stock_units <= 0;
                    return (
                      <tr key={`${item.facility}-${item.medicine_code}-${index}`}>
                        <td>
                          <strong>{item.facility}</strong>
                          <span className="cell-sub">{item.district} ({item.province})</span>
                        </td>
                        <td>
                          <strong>{item.medicine}</strong>
                          <span className="cell-sub">{item.medicine_code}</span>
                        </td>
                        <td>
                          <span className={isZero ? "text-critical font-bold" : ""}>
                            {formatNum(item.stock_units)}
                          </span>
                          <span className="cell-unit">units</span>
                        </td>
                        <td>
                          <CoverBadge days={item.lead_time_days} />
                        </td>
                        <td>
                          <span className="action-pill">
                            {isZero
                              ? "Emergency depot restock"
                              : item.lead_time_days !== null && item.lead_time_days < 3
                              ? "Expedite urgent shipment"
                              : "Check mutual-aid transfer"}
                          </span>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="inspect-btn"
                            onClick={() => onInspectMedicine(item)}
                            title="Inspect medicine inventory details"
                          >
                            <Icon name="eye" size={13} />
                            <span>Inspect</span>
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No Critical Stock Issues" icon="check-circle">
              {loading ? "Checking inventory status…" : "All monitored facilities currently report adequate stock cover."}
            </EmptyState>
          )}

          <div className="panel-footer-note">
            <Icon name="info" size={14} />
            <span>
              Stock cover is calculated as <code>current stock / daily consumption</code>.
              Tiers: <strong>Critical &lt;7 days</strong>, <strong>Moderate 7–14 days</strong>, <strong>Stable &gt;14 days</strong>.
              Always confirm physical stock count before placing emergency procurement orders.
            </span>
          </div>
        </article>

        {/* Right: Risk Health Distribution & Province Summary */}
        <div className="overview-side-column">
          {/* Risk Distribution Card */}
          <article className="panel distribution-card">
            <div className="panel-header">
              <div>
                <div className="panel-eyebrow">INVENTORY HEALTH</div>
                <h2 className="panel-title">Stock Coverage Distribution</h2>
              </div>
              <span className="tag-neutral">{formatNum(totalRecords)} records</span>
            </div>

            <div className="distribution-meter-wrap">
              <div
                className="stacked-bar-meter"
                role="img"
                aria-label={`Risk distribution: ${criticalPct}% critical, ${moderatePct}% moderate, ${stablePct}% stable, ${unknownPct}% unavailable`}
              >
                <div
                  className="meter-seg critical"
                  style={{ width: `${criticalPct}%` }}
                  title={`Critical (<7 days): ${formatNum(summary?.critical)} (${criticalPct}%)`}
                />
                <div
                  className="meter-seg moderate"
                  style={{ width: `${moderatePct}%` }}
                  title={`Moderate (7-14 days): ${formatNum(summary?.moderate)} (${moderatePct}%)`}
                />
                <div
                  className="meter-seg stable"
                  style={{ width: `${stablePct}%` }}
                  title={`Stable (>14 days): ${formatNum(summary?.stable)} (${stablePct}%)`}
                />
                <div
                  className="meter-seg unknown"
                  style={{ width: `${unknownPct}%` }}
                  title={`Cover Unavailable: ${formatNum(summary?.unknown)} (${unknownPct}%)`}
                />
              </div>

              <div className="distribution-breakdown-list">
                <div
                  className="breakdown-item clickable"
                  onClick={() => onNavigate("alerts")}
                >
                  <span className="breakdown-dot critical" />
                  <span className="breakdown-name">Critical (&lt; 7 days cover)</span>
                  <span className="breakdown-count">{formatNum(summary?.critical)}</span>
                  <span className="breakdown-pct">{criticalPct}%</span>
                </div>

                <div
                  className="breakdown-item clickable"
                  onClick={() => onNavigate("alerts")}
                >
                  <span className="breakdown-dot moderate" />
                  <span className="breakdown-name">Moderate (7–14 days cover)</span>
                  <span className="breakdown-count">{formatNum(summary?.moderate)}</span>
                  <span className="breakdown-pct">{moderatePct}%</span>
                </div>

                <div
                  className="breakdown-item clickable"
                  onClick={() => onNavigate("inventory")}
                >
                  <span className="breakdown-dot stable" />
                  <span className="breakdown-name">Stable (&gt; 14 days cover)</span>
                  <span className="breakdown-count">{formatNum(summary?.stable)}</span>
                  <span className="breakdown-pct">{stablePct}%</span>
                </div>

                <div
                  className="breakdown-item clickable"
                  onClick={() => onNavigate("inventory")}
                >
                  <span className="breakdown-dot unknown" />
                  <span className="breakdown-name">Cover Unavailable (No consumption)</span>
                  <span className="breakdown-count">{formatNum(summary?.unknown)}</span>
                  <span className="breakdown-pct">{unknownPct}%</span>
                </div>
              </div>
            </div>

            <div className="distribution-card-footer">
              <span>Reporting snapshot: <strong>{summary?.reporting_date || "—"}</strong></span>
              <ProvenanceBadge
                item={{
                  method: "rule_based_fallback",
                  data_source: summary?.data_source || "synthetic",
                  is_synthetic: Boolean(summary?.is_synthetic),
                  provenance_status: summary?.provenance_status || "uploaded_unverified",
                }}
              />
            </div>
          </article>

          {/* Regional Situation Summary */}
          {provinceSummary.length > 0 && (
            <article className="panel regional-summary-card">
              <div className="panel-header">
                <div>
                  <div className="panel-eyebrow">REGIONAL OVERVIEW</div>
                  <h3 className="panel-title-sm">Critical Facilities by Province</h3>
                </div>
              </div>
              <div className="regional-list">
                {provinceSummary.map(([prov, stats]) => (
                  <div key={prov} className="regional-row">
                    <span className="regional-name">{prov} Province</span>
                    <div className="regional-stats">
                      <span className="regional-total">{stats.total} facilities</span>
                      {stats.critical > 0 ? (
                        <span className="regional-critical-badge">
                          {stats.critical} critical
                        </span>
                      ) : (
                        <span className="regional-ok-badge">All stable</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </article>
          )}
        </div>
      </section>

      {/* Rebalancing Banner */}
      <section className="transfer-teaser-banner">
        <div className="transfer-teaser-icon">
          <Icon name="truck" size={22} />
        </div>
        <div className="transfer-teaser-text">
          <h3>Stock Rebalancing Opportunities Available</h3>
          <p>
            {transfers.length > 0
              ? `${formatNum(transfers.length)} potential stock transfers identified between overstocked facilities (>30 days cover) and facilities facing imminent stockouts (<14 days cover).`
              : "No immediate inter-facility transfers identified."}
          </p>
        </div>
        <button
          type="button"
          className="secondary-action-button"
          onClick={() => onNavigate("transfers")}
        >
          <span>Explore Transfers</span>
          <Icon name="arrow-right" size={14} />
        </button>
      </section>
    </div>
  );
}
