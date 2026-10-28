import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icons";

interface EmptyStateProps {
  title?: string;
  children: ReactNode;
  icon?: IconName;
  actionText?: string;
  onAction?: () => void;
}

export function EmptyState({
  title,
  children,
  icon = "file",
  actionText,
  onAction,
}: EmptyStateProps) {
  return (
    <div className="empty-state">
      <div className="empty-icon-wrap">
        <Icon name={icon} size={24} />
      </div>
      {title && <h3 className="empty-title">{title}</h3>}
      <div className="empty-message">{children}</div>
      {actionText && onAction && (
        <button
          type="button"
          className="empty-action-button"
          onClick={onAction}
        >
          {actionText}
        </button>
      )}
    </div>
  );
}
