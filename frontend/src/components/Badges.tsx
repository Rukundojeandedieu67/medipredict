import type { ProvenanceStatus, RiskRecord, VerificationBlock } from "../types";
import { Icon } from "./Icons";

export function RiskBadge({ risk }: { risk: string }) {
  const level = risk.toLowerCase();
  const iconName =
    level === "critical"
      ? "alert"
      : level === "moderate" || level === "warning"
      ? "alert-triangle"
      : level === "stable"
      ? "check"
      : "info";

  return (
    <span className={`risk-badge ${level}`} role="status">
      <Icon name={iconName} size={12} />
      <span>{risk.toUpperCase()}</span>
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: "critical" | "warning" }) {
  return (
    <span className={`severity-badge ${severity}`} role="status">
      <Icon name={severity === "critical" ? "alert" : "alert-triangle"} size={12} />
      <span>{severity === "critical" ? "Critical Priority" : "Warning"}</span>
    </span>
  );
}

export function CoverBadge({ days }: { days: number | null | undefined }) {
  if (days === null || days === undefined || !Number.isFinite(days)) {
    return (
      <span className="cover-badge unavailable" title="Consumption is missing or 0; cover cannot be calculated">
        <Icon name="help-circle" size={12} />
        <span>Cover Unavailable</span>
      </span>
    );
  }

  const rounded = Math.round(days * 10) / 10;
  let tone = "stable";
  if (rounded < 7) {
    tone = "critical";
  } else if (rounded <= 14) {
    tone = "warning";
  }

  return (
    <span className={`cover-badge ${tone}`}>
      <span className="cover-value">{rounded}</span>
      <span className="cover-unit">days</span>
    </span>
  );
}

export function ProvenanceBadge({
  item,
}: {
  item: Pick<
    RiskRecord,
    "method" | "data_source" | "is_synthetic" | "provenance_status"
  > & { verification?: VerificationBlock | null };
}) {
  return (
    <div className="provenance-badges">
      {item.method === "rule_based_fallback" && (
        <span
          className="assessment-badge method-badge"
          title="Rule-based days-of-cover estimate; this is not a trained AI forecast."
        >
          Rule-based estimate
        </span>
      )}
      {item.provenance_status === "synthetic" ? (
        <span
          className="assessment-badge synthetic-badge"
          title="Synthetic demonstration dataset"
        >
          Synthetic
        </span>
      ) : item.provenance_status === "verified" ? (
        <span
          className="assessment-badge source-badge verified"
          title="Dataset origin was checked against an approved source."
        >
          Verified Source
        </span>
      ) : (
        <span
          className="assessment-badge source-badge uploaded"
          title="Provided through CSV upload; source verification is not required for assessment."
        >
          Uploaded
        </span>
      )}
      {item.provenance_status === "verified" && item.verification && (
        <VerificationCard verification={item.verification} />
      )}
    </div>
  );
}

function displayValue(value: string | null | undefined): string {
  return value?.trim() || "n/a";
}

function shortHash(value: string | null | undefined): string {
  const hash = value?.trim();
  return hash ? hash.slice(0, 12) : "n/a";
}

export function ProvenanceStatusBadge({ status }: { status: ProvenanceStatus }) {
  if (status === "synthetic") {
    return (
      <span className="assessment-badge synthetic-badge" title="Synthetic demonstration data">
        Synthetic
      </span>
    );
  }
  if (status === "verified") {
    return (
      <span className="assessment-badge source-badge verified" title="Dataset origin was checked against an approved source.">
        Verified Source
      </span>
    );
  }
  return (
    <span
      className="assessment-badge source-badge uploaded"
      title="Provided through CSV upload; source verification is optional."
    >
      Uploaded
    </span>
  );
}

export function VerificationCard({
  verification,
}: {
  verification: VerificationBlock;
}) {
  return (
    <div className="verification-card">
      <div><strong>Source:</strong> {displayValue(verification.source.name)}, {displayValue(verification.source.organization)}, {displayValue(verification.source.system)}</div>
      <div><strong>Verification:</strong> {displayValue(verification.verification_method)}</div>
      <div>
        <strong>Dataset/reference:</strong> {displayValue(verification.verification_reference)} · {displayValue(verification.dataset_id)} · SHA-256 {shortHash(verification.dataset_sha256)}
      </div>
      <div>
        <strong>Reporting period:</strong> {displayValue(verification.reporting_period_start)} to {displayValue(verification.reporting_period_end)}
      </div>
      <div>
        <strong>Verified by / on:</strong> {displayValue(verification.verified_by)} · {displayValue(verification.verified_at)}
        {verification.single_party && ` · ${displayValue(verification.identity_note)}`}
      </div>
    </div>
  );
}

export function AlertStatusBadge({
  status,
  onClick,
}: {
  status: "open" | "acknowledged" | "resolved";
  onClick?: () => void;
}) {
  const labels: Record<string, string> = {
    open: "Open / Action Required",
    acknowledged: "Acknowledged",
    resolved: "Resolved / Rebalanced",
  };

  const icons: Record<string, "alert-triangle" | "clock" | "check-circle"> = {
    open: "alert-triangle",
    acknowledged: "clock",
    resolved: "check-circle",
  };

  return (
    <button
      type="button"
      className={`status-pill status-${status} ${onClick ? "interactive" : ""}`}
      onClick={onClick}
      disabled={!onClick}
      title={onClick ? "Click to toggle resolution status" : undefined}
    >
      <Icon name={icons[status]} size={12} />
      <span>{labels[status]}</span>
      {onClick && <span className="status-toggle-hint">change</span>}
    </button>
  );
}
