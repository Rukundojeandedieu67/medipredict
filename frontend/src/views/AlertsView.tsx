import { useState, useMemo } from "react";
import type { StockAlert, RiskRecord } from "../types";
import { Icon } from "../components/Icons";
import { SeverityBadge, CoverBadge, ProvenanceBadge, AlertStatusBadge } from "../components/Badges";
import { ProjectionSparkline } from "../components/ProjectionSparkline";
import { EmptyState } from "../components/EmptyState";

interface AlertsViewProps {
  alerts: StockAlert[];
  risks: RiskRecord[];
  loading: boolean;
  alertStatuses: Record<string, "open" | "acknowledged" | "resolved">;
  onToggleStatus: (alertId: string) => void;
  onInspectMedicine: (item: RiskRecord) => void;
  onNavigateToTransfers: () => void;
}

function formatNum(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat().format(value);
}

export function AlertsView({
  alerts,
  risks,
  loading,
  alertStatuses,
  onToggleStatus,
  onInspectMedicine,
  onNavigateToTransfers,
}: AlertsViewProps) {
  const [search, setSearch] = useState("");
  const [severityFilter, setSeverityFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  // Summary counts
  const criticalCount = useMemo(() => alerts.filter((a) => a.severity === "critical").length, [alerts]);
  const warningCount = useMemo(() => alerts.filter((a) => a.severity === "warning").length, [alerts]);
  const resolvedCount = useMemo(() => {
    return alerts.filter((a) => alertStatuses[a.alert_id] === "resolved").length;
  }, [alerts, alertStatuses]);

  // Lookup corresponding RiskRecord for modal inspection
  const riskMap = useMemo(() => {
    const map = new Map<string, RiskRecord>();
    risks.forEach((r) => {
      map.set(`${r.facility.trim().toLowerCase()}|${r.medicine_code.trim().toLowerCase()}`, r);
    });
    return map;
  }, [risks]);

  const filteredAlerts = useMemo(() => {
    const q = search.trim().toLowerCase();

    return alerts.filter((alert) => {
      // Search
      if (q) {
        const hay = `${alert.facility} ${alert.district} ${alert.medicine} ${alert.medicine_code} ${alert.message}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }

      // Severity
      if (severityFilter !== "all" && alert.severity !== severityFilter) {
        return false;
      }

      // Alert Type
      if (typeFilter !== "all" && alert.alert_type !== typeFilter) {
        return false;
      }

      // Status
      const currentStatus = alertStatuses[alert.alert_id] || "open";
      if (statusFilter !== "all" && currentStatus !== statusFilter) {
        return false;
      }

      return true;
    });
  }, [alerts, search, severityFilter, typeFilter, statusFilter, alertStatuses]);

  const resetFilters = () => {
    setSearch("");
    setSeverityFilter("all");
    setTypeFilter("all");
    setStatusFilter("all");
  };

  const getRecommendedAction = (alert: StockAlert) => {
    if (alert.alert_type === "stockout") {
      return {
        step: "Emergency depot dispatch request; inspect physical shelf count.",
        tone: "critical",
      };
    }
    if (alert.alert_type === "critical_stock") {
      return {
        step: "Expedite delivery within 48h or initiate mutual aid transfer from nearby facility.",
        tone: "critical",
      };
    }
    if (alert.alert_type === "low_stock") {
      return {
        step: "Include in upcoming routine distribution; verify consumption trends.",
        tone: "warning",
      };
    }
    if (alert.alert_type === "cover_unavailable") {
      return {
        step: "Audit monthly consumption logs; notify facility data officer.",
        tone: "neutral",
      };
    }
    return {
      step: "Verify source record integrity before taking supply-chain actions.",
      tone: "neutral",
    };
  };

  return (
    <div className="alerts-view-container">
      {/* Header */}
      <section className="section-header">
        <div>
          <div className="eyebrow-pill">
            <span className="eyebrow-dot" />
            EARLY-WARNING ACTION REGISTER
          </div>
          <h1 className="page-title">
            Stock Availability Alerts<span className="heading-period">.</span>
          </h1>
          <p className="page-subtitle">
            Immediate actionable warnings for stockouts, low cover, and missing data. Review why each alert was raised, take action, and track resolution.
          </p>
        </div>
        <div className="header-meta-badge">
          <span className="meta-count">{formatNum(alerts.length)}</span>
          <span className="meta-label">active warnings</span>
        </div>
      </section>

      {/* Operational Notice */}
      <div className="notice-banner">
        <div className="notice-icon-box">
          <Icon name="info" size={18} />
        </div>
        <div className="notice-body">
          <strong>Transparent stock projections &amp; limitations:</strong>
          <p>
            Remaining stock after 7 and 14 days is estimated strictly from reported stock and average daily consumption,
            assuming constant use and zero incoming deliveries. These are transparent arithmetic scenarios, not machine-learning forecasts.
            Always confirm physical stock and pending deliveries before taking operational action.
          </p>
        </div>
      </div>

      {/* KPI Cards Strip */}
      <div className="alerts-kpi-strip">
        <div
          className={`alerts-kpi-card ${severityFilter === "critical" ? "active" : ""}`}
          onClick={() => setSeverityFilter(severityFilter === "critical" ? "all" : "critical")}
        >
          <div className="kpi-icon-wrap rose">
            <Icon name="alert-triangle" size={16} />
          </div>
          <div className="kpi-content">
            <span className="kpi-label">Critical Priority</span>
            <strong className="kpi-value text-critical">{formatNum(criticalCount)}</strong>
            <span className="kpi-hint">Stockouts &amp; &lt;7d cover</span>
          </div>
        </div>

        <div
          className={`alerts-kpi-card ${severityFilter === "warning" ? "active" : ""}`}
          onClick={() => setSeverityFilter(severityFilter === "warning" ? "all" : "warning")}
        >
          <div className="kpi-icon-wrap amber">
            <Icon name="alert" size={16} />
          </div>
          <div className="kpi-content">
            <span className="kpi-label">Low Cover Warnings</span>
            <strong className="kpi-value text-warning">{formatNum(warningCount)}</strong>
            <span className="kpi-hint">7–14 days remaining</span>
          </div>
        </div>

        <div
          className={`alerts-kpi-card ${statusFilter === "resolved" ? "active" : ""}`}
          onClick={() => setStatusFilter(statusFilter === "resolved" ? "all" : "resolved")}
        >
          <div className="kpi-icon-wrap mint">
            <Icon name="check-circle" size={16} />
          </div>
          <div className="kpi-content">
            <span className="kpi-label">Marked Resolved</span>
            <strong className="kpi-value text-stable">{formatNum(resolvedCount)}</strong>
            <span className="kpi-hint">Handled in this session</span>
          </div>
        </div>
      </div>

      {/* Main Alert Register Panel */}
      <div className="panel alerts-panel">
        {/* Filters Toolbar */}
        <div className="inventory-toolbar">
          <div className="search-input-wrap">
            <Icon name="search" size={16} />
            <input
              type="text"
              className="search-input"
              placeholder="Search alert by facility, district, medicine, or reason…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {search && (
              <button
                type="button"
                className="clear-search-btn"
                onClick={() => setSearch("")}
                aria-label="Clear search"
              >
                <Icon name="close" size={14} />
              </button>
            )}
          </div>

          <div className="filters-group">
            {/* Severity filter */}
            <div className="filter-select-wrap">
              <label htmlFor="alert-filter-severity" className="filter-label">Severity:</label>
              <select
                id="alert-filter-severity"
                value={severityFilter}
                onChange={(e) => setSeverityFilter(e.target.value)}
              >
                <option value="all">All Severities</option>
                <option value="critical">Critical Priority Only</option>
                <option value="warning">Warning Only</option>
              </select>
            </div>

            {/* Alert type */}
            <div className="filter-select-wrap">
              <label htmlFor="alert-filter-type" className="filter-label">Alert Type:</label>
              <select
                id="alert-filter-type"
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
              >
                <option value="all">All Alert Types</option>
                <option value="stockout">Out of Stock (0 units)</option>
                <option value="critical_stock">Critical Stock (&lt;7 days)</option>
                <option value="low_stock">Low Stock (7–14 days)</option>
                <option value="cover_unavailable">Cover Unavailable</option>
                <option value="invalid_data">Invalid Data</option>
              </select>
            </div>

            {/* Resolution Status */}
            <div className="filter-select-wrap">
              <label htmlFor="alert-filter-status" className="filter-label">Status:</label>
              <select
                id="alert-filter-status"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="all">All Statuses</option>
                <option value="open">Open / Action Required</option>
                <option value="acknowledged">Acknowledged</option>
                <option value="resolved">Resolved</option>
              </select>
            </div>

            {(search || severityFilter !== "all" || typeFilter !== "all" || statusFilter !== "all") && (
              <button
                type="button"
                className="reset-filters-btn"
                onClick={resetFilters}
              >
                <Icon name="close" size={13} />
                <span>Reset</span>
              </button>
            )}
          </div>
        </div>

        {/* Alerts List */}
        {loading && !alerts.length ? (
          <div className="table-loading-state">
            <Icon name="refresh" size={24} className="spin-icon" />
            <p>Loading active stock alerts…</p>
          </div>
        ) : filteredAlerts.length > 0 ? (
          <div className="alerts-card-list">
            {filteredAlerts.map((alert) => {
              const status = alertStatuses[alert.alert_id] || "open";
              const action = getRecommendedAction(alert);
              const matchingRisk = riskMap.get(
                `${alert.facility.trim().toLowerCase()}|${alert.medicine_code.trim().toLowerCase()}`
              );

              return (
                <article
                  key={alert.alert_id}
                  className={`alert-card-item severity-${alert.severity} status-${status}`}
                >
                  <div className="alert-card-top-row">
                    <div className="alert-card-title-group">
                      <div className="alert-badges-row">
                        <SeverityBadge severity={alert.severity} />
                        <span className="alert-type-chip">
                          {alert.alert_type.replaceAll("_", " ").toUpperCase()}
                        </span>
                        <CoverBadge days={alert.lead_time_days} />
                      </div>
                      <h3 className="alert-medicine-title">
                        {alert.medicine}{" "}
                        <span className="alert-code-tag">{alert.medicine_code}</span>
                      </h3>
                      <div className="alert-location-row">
                        <Icon name="building" size={13} />
                        <strong>{alert.facility}</strong>
                        <span className="loc-sep">·</span>
                        <span>{alert.district} District</span>
                        <span className="loc-sep">·</span>
                        <span className="reporting-date-tag">Snapshot: {alert.reporting_date}</span>
                      </div>
                    </div>

                    <div className="alert-card-top-actions">
                      <AlertStatusBadge
                        status={status}
                        onClick={() => onToggleStatus(alert.alert_id)}
                      />
                    </div>
                  </div>

                  {/* Why alert was raised */}
                  <div className="alert-reason-banner">
                    <div className="reason-icon">
                      <Icon name="alert-triangle" size={15} />
                    </div>
                    <div className="reason-text">
                      <strong>Root Cause / Why this alert was raised:</strong>
                      <p>{alert.message}</p>
                    </div>
                  </div>

                  {/* Underlying values grid */}
                  <div className="alert-metrics-strip">
                    <div className="alert-metric-col">
                      <span className="alert-metric-label">Stock Balance</span>
                      <strong className={`alert-metric-val ${alert.stock_units === 0 ? "text-critical" : ""}`}>
                        {formatNum(alert.stock_units)} <small>units</small>
                      </strong>
                    </div>

                    <div className="alert-metric-col">
                      <span className="alert-metric-label">Daily Consumption</span>
                      <strong className="alert-metric-val">
                        {formatNum(alert.daily_consumption)} <small>units/day</small>
                      </strong>
                    </div>

                    <div className="alert-metric-col">
                      <span className="alert-metric-label">Estimated Stock Cover</span>
                      <strong className={`alert-metric-val ${alert.lead_time_days !== null && alert.lead_time_days < 7 ? "text-critical" : ""}`}>
                        {alert.lead_time_days !== null ? `${Math.round(alert.lead_time_days * 10) / 10} days` : "Unavailable"}
                      </strong>
                    </div>

                    <div className="alert-metric-col trajectory-col">
                      <span className="alert-metric-label">Estimated Depletion</span>
                      <ProjectionSparkline
                        current={alert.stock_units}
                        after7Days={alert.estimated_stock_after_7_days}
                        after14Days={alert.estimated_stock_after_14_days}
                        label={`${alert.facility} ${alert.medicine}`}
                        compact
                      />
                    </div>
                  </div>

                  {/* Recommended next step and card footer */}
                  <div className="alert-card-footer">
                    <div className="recommended-action-box">
                      <span className="action-step-label">Recommended Next Action:</span>
                      <span className="action-step-text">{action.step}</span>
                    </div>

                    <div className="alert-card-buttons">
                      {alert.lead_time_days !== null && alert.lead_time_days < 14 && (
                        <button
                          type="button"
                          className="btn-transfer-link"
                          onClick={onNavigateToTransfers}
                        >
                          <Icon name="truck" size={13} />
                          <span>Check Transfers</span>
                        </button>
                      )}
                      {matchingRisk && (
                        <button
                          type="button"
                          className="inspect-btn"
                          onClick={() => onInspectMedicine(matchingRisk)}
                        >
                          <Icon name="eye" size={13} />
                          <span>Full Audit</span>
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="alert-provenance-tag">
                    <ProvenanceBadge
                      item={{
                        method: "rule_based_fallback",
                        data_source: alert.data_source,
                        is_synthetic: alert.is_synthetic,
                        provenance_status: alert.provenance_status,
                      }}
                    />
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <EmptyState
            title="No Active Alerts Found"
            icon="check-circle"
            actionText="Reset Filters"
            onAction={resetFilters}
          >
            No alerts matched your current search and severity filters.
          </EmptyState>
        )}

        <div className="panel-footer-meta">
          <span>Alerts evaluate the latest snapshot record per facility and medicine.</span>
          <span>Rule-based fallback estimation · Not a predictive ML forecast</span>
        </div>
      </div>
    </div>
  );
}
