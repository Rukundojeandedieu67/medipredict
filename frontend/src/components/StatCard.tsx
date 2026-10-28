import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icons";

interface StatCardProps {
  label: string;
  value: string;
  note: string;
  icon: IconName;
  tone: "mint" | "rose" | "blue" | "amber" | "neutral";
  tooltip?: string;
  badge?: ReactNode;
  onClick?: () => void;
}

export function StatCard({
  label,
  value,
  note,
  icon,
  tone,
  tooltip,
  badge,
  onClick,
}: StatCardProps) {
  return (
    <article
      className={`stat-card tone-${tone} ${onClick ? "clickable" : ""}`}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
    >
      <div className="stat-card-header">
        <span className="stat-label">
          {label}
          {tooltip && (
            <span className="stat-info-icon" title={tooltip}>
              <Icon name="info" size={13} />
            </span>
          )}
        </span>
        <div className={`stat-icon ${tone}`}>
          <Icon name={icon} size={18} />
        </div>
      </div>

      <div className="stat-value-row">
        <span className="stat-value">{value}</span>
        {badge && <span className="stat-badge-wrap">{badge}</span>}
      </div>

      <p className="stat-note">{note}</p>
    </article>
  );
}
