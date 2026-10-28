import { useEffect } from "react";
import type { RiskRecord, TransferCandidate } from "../types";
import { Icon } from "./Icons";
import { RiskBadge, ProvenanceBadge, CoverBadge, AlertStatusBadge } from "./Badges";
import { ProjectionSparkline } from "./ProjectionSparkline";

interface MedicineDetailModalProps {
  item: RiskRecord | null;
  onClose: () => void;
  transfers?: TransferCandidate[];
  onNavigateToTransfers?: () => void;
  alertStatus?: "open" | "acknowledged" | "resolved";
  onToggleStatus?: () => void;
}

function formatNum(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat().format(value);
}

export function MedicineDetailModal({
  item,
  onClose,
  transfers = [],
  onNavigateToTransfers,
  alertStatus = "open",
  onToggleStatus,
}: MedicineDetailModalProps) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  if (!item) return null;

  const relevantTransfers = transfers.filter(
    (t) =>
      t.medicine.toLowerCase() === item.medicine.toLowerCase() ||
      (t.recipient_facility === item.facility && t.available_units > 0)
  );

  const getRecommendedAction = () => {
    const cover = item.lead_time_days;
    const stock = item.stock_units;

    if (stock <= 0) {
      return {
        priority: "Immediate",
        headline: "Emergency stockout response required",
        detail:
          "Stock is exhausted. Request expedited emergency supply from regional depot or arrange mutual aid transfer from an overstocked facility.",
        tone: "critical",
      };
    }
    if (cover !== null && cover < 7) {
      return {
        priority: "Urgent",
        headline: "Expedite replenishment within 48 hours",
        detail:
          "Available inventory is under 7 days of consumption. Place an urgent order and verify delivery schedule.",
        tone: "critical",
      };
    }
    if (cover !== null && cover <= 14) {
      return {
        priority: "Moderate",
        headline: "Schedule routine re-order",
        detail:
          "Stock cover is between 7 and 14 days. Include this item in the weekly facility order to prevent stockout.",
        tone: "warning",
      };
    }
    if (cover === null || item.daily_consumption <= 0) {
      return {
        priority: "Data Quality",
        headline: "Audit consumption reporting records",
        detail:
          "Average daily consumption is reported as zero or missing. Confirm physical inventory ledger to restore cover estimation.",
        tone: "neutral",
      };
    }
    return {
      priority: "Routine",
      headline: "Inventory levels stable",
      detail:
        "Stock cover exceeds 14 days. Monitor regular monthly dispensing and maintain standard storage controls.",
      tone: "stable",
    };
  };

  const action = getRecommendedAction();

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="modal-med-title">
      <div className="modal-sheet" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div className="modal-header-info">
            <div className="modal-badges-row">
              <RiskBadge risk={item.risk_level} />
              <CoverBadge days={item.lead_time_days} />
              {onToggleStatus && (
                <AlertStatusBadge status={alertStatus} onClick={onToggleStatus} />
              )}
            </div>
            <h2 id="modal-med-title" className="modal-title">
              {item.medicine}
            </h2>
            <div className="modal-meta-row">
              <span className="modal-code">Product Code: {item.medicine_code}</span>
              <span className="meta-separator">·</span>
              <span className="modal-facility">
                <Icon name="building" size={13} /> {item.facility}
              </span>
              <span className="meta-separator">·</span>
              <span className="modal-location">
                {item.district}, {item.province} Province
              </span>
            </div>
          </div>
          <button
            type="button"
            className="modal-close-button"
            onClick={onClose}
            aria-label="Close medicine detail view"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Body content */}
        <div className="modal-body">
          {/* Operational action alert */}
          <section className={`action-card tone-${action.tone}`}>
            <div className="action-card-icon">
              <Icon name="alert-triangle" size={20} />
            </div>
            <div className="action-card-content">
              <div className="action-priority-tag">RECOMMENDED ACTION · {action.priority.toUpperCase()}</div>
              <h3 className="action-headline">{action.headline}</h3>
              <p className="action-detail">{action.detail}</p>
            </div>
          </section>

          {/* Key Metrics Grid */}
          <div className="detail-metrics-grid">
            <div className="detail-metric-card">
              <span className="metric-label">Current Stock on Hand</span>
              <div className="metric-val-wrap">
                <strong className="metric-val">{formatNum(item.stock_units)}</strong>
                <span className="metric-unit">units</span>
              </div>
              <span className="metric-caption">Reported physical balance</span>
            </div>

            <div className="detail-metric-card">
              <span className="metric-label">Average Daily Consumption</span>
              <div className="metric-val-wrap">
                <strong className="metric-val">{formatNum(item.daily_consumption)}</strong>
                <span className="metric-unit">units / day</span>
              </div>
              <span className="metric-caption">Facility daily average use</span>
            </div>

            <div className="detail-metric-card">
              <span className="metric-label">Estimated Days of Cover</span>
              <div className="metric-val-wrap">
                <strong className={`metric-val ${item.lead_time_days !== null && item.lead_time_days < 7 ? "text-critical" : ""}`}>
                  {item.lead_time_days !== null ? Math.round(item.lead_time_days * 10) / 10 : "n/a"}
                </strong>
                <span className="metric-unit">days</span>
              </div>
              <span className="metric-caption">Stock / Daily consumption</span>
            </div>

            <div className="detail-metric-card">
              <span className="metric-label">Resolution Status</span>
              <div className="metric-val-wrap">
                <strong className="metric-val-text">{alertStatus.toUpperCase()}</strong>
              </div>
              <span className="metric-caption">
                {onToggleStatus ? "Click badge above to toggle" : "Operational state"}
              </span>
            </div>
          </div>

          {/* Stock Depletion Projection */}
          <section className="detail-section">
            <div className="section-title-row">
              <h4>Stock Trajectory Projection</h4>
              <span className="section-subtitle">Arithmetic scenario</span>
            </div>
            <div className="detail-projection-box">
              <ProjectionSparkline
                current={item.stock_units}
                after7Days={item.estimated_stock_after_7_days}
                after14Days={item.estimated_stock_after_14_days}
                label={`${item.facility} ${item.medicine}`}
              />
              <div className="projection-explanation">
                <p>
                  <strong>Projection assumptions:</strong> Estimated remaining stock after 7 and 14 days
                  is computed as <code>current stock - (average daily consumption × days)</code>.
                  This simple scenario assumes zero incoming deliveries and a constant rate of use.
                  Always verify pending purchase orders or incoming depot transfers before taking action.
                </p>
              </div>
            </div>
          </section>

          {/* Potential Transfer Rebalancing */}
          {relevantTransfers.length > 0 && (
            <section className="detail-section">
              <div className="section-title-row">
                <h4>Stock Rebalancing Opportunities</h4>
                <span className="section-subtitle">Matching transfer donor</span>
              </div>
              <div className="transfer-match-list">
                {relevantTransfers.map((t, idx) => (
                  <div key={idx} className="transfer-match-card">
                    <div className="transfer-match-header">
                      <div className="transfer-match-donor">
                        <small>AVAILABLE DONOR</small>
                        <strong>{t.donor_facility}</strong>
                        <span>{t.donor_district} ({Math.round(t.donor_lead_time_days)}d cover)</span>
                      </div>
                      <div className="transfer-match-arrow">
                        <Icon name="arrow-right" size={16} />
                      </div>
                      <div className="transfer-match-amount">
                        <small>SUGGESTED TRANSFER</small>
                        <strong>{formatNum(t.requested_units)} units</strong>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              {onNavigateToTransfers && (
                <button
                  type="button"
                  className="view-transfers-link"
                  onClick={() => {
                    onClose();
                    onNavigateToTransfers();
                  }}
                >
                  <Icon name="truck" size={14} /> Open Stock Transfers view
                </button>
              )}
            </section>
          )}

          {/* Assessment & Data Integrity Disclaimers */}
          <section className="detail-section provenance-section">
            <div className="section-title-row">
              <h4>Data Provenance &amp; Verification</h4>
            </div>
            <div className="provenance-details-box">
              <div className="provenance-row">
                <span>Assessment Method:</span>
                <strong>Rule-based days-of-cover fallback logic</strong>
              </div>
              <div className="provenance-row">
                <span>Model Serving:</span>
                <span>Not enabled (predictive ML models are not validated for operational serving)</span>
              </div>
              <div className="provenance-row">
                <span>Confidence:</span>
                <span>{item.confidence_note || "Fixed threshold evaluation; not an empirical probability."}</span>
              </div>
              <div className="provenance-row">
                <span>Data Source:</span>
                <ProvenanceBadge item={item} />
              </div>
              <div className="provenance-row">
                <span>District Indicators (NISR Context):</span>
                <span>
                  Under-5 pop: {formatNum(item.under5_population)} · Poverty: {item.poverty_rate}% · Malaria: {item.malaria_prevalence}%
                  <em className="unverified-tag"> (Unverified seed values)</em>
                </span>
              </div>
            </div>
          </section>
        </div>

        {/* Modal footer */}
        <div className="modal-footer">
          <span className="modal-footer-note">
            MediPredict Rwanda · Operational Supply Chain Support
          </span>
          <button type="button" className="secondary-button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
