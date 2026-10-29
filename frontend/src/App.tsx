import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import type { RiskRecord, StockAlert, Summary, TransferCandidate, TrustMetrics, UploadResult } from "./types";
import { Icon, type IconName } from "./components/Icons";
import { MedicineDetailModal } from "./components/MedicineDetailModal";
import { OverviewView } from "./views/OverviewView";
import { InventoryView } from "./views/InventoryView";
import { AlertsView } from "./views/AlertsView";
import { RiskRegisterView } from "./views/RiskRegisterView";
import { TransfersView } from "./views/TransfersView";
import { TrustView } from "./views/TrustView";
import { UploadView } from "./views/UploadView";
import { LoginView } from "./components/LoginView";

type View = "overview" | "inventory" | "alerts" | "risk" | "transfers" | "trust" | "upload";
interface AuthUser {
  id: string;
  email: string;
  role: "admin" | "user";
}

interface AuthSession {
  user: AuthUser;
  csrf_token: string;
}

interface NavItem {
  id: View;
  label: string;
  icon: IconName;
  badgeCount?: (alerts: StockAlert[], transfers: TransferCandidate[]) => number | null;
}

const navItems: NavItem[] = [
  { id: "overview", label: "Overview", icon: "grid" },
  { id: "inventory", label: "Inventory", icon: "package" },
  {
    id: "alerts",
    label: "Stock Alerts",
    icon: "alert",
    badgeCount: (alerts) => (alerts.length > 0 ? alerts.length : null),
  },
  { id: "risk", label: "Risk Register", icon: "pulse" },
  {
    id: "transfers",
    label: "Stock Transfers",
    icon: "truck",
    badgeCount: (_, transfers) => (transfers.length > 0 ? transfers.length : null),
  },
  { id: "trust", label: "Model Insights", icon: "shield" },
  { id: "upload", label: "Upload Data", icon: "upload" },
];

async function getResponseError(response: Response): Promise<string> {
  const body = await response.text();
  if (body) {
    try {
      const payload = JSON.parse(body) as {
        detail?: unknown;
        message?: unknown;
      };
      if (typeof payload.detail === "string") return payload.detail;
      if (typeof payload.message === "string") return payload.message;
      if (typeof payload.detail === "object" && payload.detail !== null) {
        const detail = payload.detail as {
          message?: unknown;
          validation?: {
            errors?: unknown;
            total_counts?: { errors?: unknown };
          };
        };
        const validation = detail.validation;
        if (Array.isArray(validation?.errors) && validation.errors.length > 0) {
          const issues = validation.errors
            .filter(
              (issue): issue is {
                row_number?: number | null;
                column?: string;
                code?: string;
                message?: string;
              } =>
                typeof issue === "object" &&
                issue !== null &&
                "message" in issue &&
                typeof issue.message === "string"
            );
          const shownIssues = issues.slice(0, 5).map((issue) => {
            const location = [
              issue.row_number ? `row ${issue.row_number}` : "",
              issue.column ? `column "${issue.column}"` : "",
            ]
              .filter(Boolean)
              .join(", ");
            const code = issue.code ? ` [${issue.code}]` : "";
            return `${location ? `${location}: ` : ""}${issue.message}${code}`;
          });
          const totalErrors =
            typeof validation.total_counts?.errors === "number"
              ? validation.total_counts.errors
              : issues.length;
          const remaining = Math.max(0, totalErrors - shownIssues.length);
          const summary =
            typeof detail.message === "string"
              ? detail.message
              : "CSV validation failed.";
          return `${summary} ${shownIssues.join(" ")}${
            remaining > 0 ? ` And ${remaining} more validation error(s).` : ""
          }`;
        }
        if (typeof detail.message === "string") return detail.message;
      }
      if (Array.isArray(payload.detail)) {
        return payload.detail
          .map((item: unknown) => {
            if (typeof item === "object" && item !== null && "msg" in item) {
              return String((item as { msg: unknown }).msg);
            }
            return String(item);
          })
          .join("; ");
      }
    } catch {
      if (!body.trimStart().startsWith("<")) return body;
    }
  }
  return `Request failed (${response.status}${response.statusText ? ` ${response.statusText}` : ""})`;
}

async function fetchApi<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1/${path}`, { credentials: "same-origin" });
  if (!response.ok) throw new Error(await getResponseError(response));
  return response.json() as Promise<T>;
}

export function App() {
  const [authStatus, setAuthStatus] = useState<"checking" | "signed-out" | "signed-in">("checking");
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [csrfToken, setCsrfToken] = useState("");
  const [authConfigurationError, setAuthConfigurationError] = useState("");
  const [authActionError, setAuthActionError] = useState("");
  const [userManagementOpen, setUserManagementOpen] = useState(false);
  const [newUserEmail, setNewUserEmail] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [userManagementMessage, setUserManagementMessage] = useState("");
  const [userManagementError, setUserManagementError] = useState("");
  const [creatingUser, setCreatingUser] = useState(false);
  const [view, setView] = useState<View>("overview");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [risks, setRisks] = useState<RiskRecord[]>([]);
  const [alerts, setAlerts] = useState<StockAlert[]>([]);
  const [transfers, setTransfers] = useState<TransferCandidate[]>([]);
  const [metrics, setMetrics] = useState<TrustMetrics | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [apiConnected, setApiConnected] = useState(false);
  const [loading, setLoading] = useState(true);

  // Risk Register internal state
  const [riskQuery, setRiskQuery] = useState("");
  const [riskFilter, setRiskFilter] = useState("All risk levels");

  // Upload state
  const [upload, setUpload] = useState<UploadResult | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [uploading, setUploading] = useState(false);

  // Medicine inspection modal state
  const [selectedMedicine, setSelectedMedicine] = useState<RiskRecord | null>(null);

  // Alert resolution status tracking (persisted in session)
  const [alertStatuses, setAlertStatuses] = useState<Record<string, "open" | "acknowledged" | "resolved">>(() => {
    try {
      const stored = localStorage.getItem("medipredict_alert_statuses");
      return stored ? JSON.parse(stored) : {};
    } catch {
      return {};
    }
  });

  // Mobile sidebar open state
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    let active = true;
    void fetch("/api/v1/auth/me", { credentials: "same-origin" })
      .then(async (response) => {
        if (response.status === 401) {
          if (active) setAuthStatus("signed-out");
          return;
        }
        if (!response.ok) throw new Error(await getResponseError(response));
        const session = (await response.json()) as AuthSession;
        if (active) {
          setAuthUser(session.user);
          setCsrfToken(session.csrf_token);
          setAuthStatus("signed-in");
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setAuthConfigurationError(
            error instanceof Error ? error.message : "Authentication service is unavailable."
          );
          setAuthStatus("signed-out");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const signIn = async (email: string, password: string) => {
    const response = await fetch("/api/v1/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!response.ok) throw new Error(await getResponseError(response));
    const session = (await response.json()) as AuthSession;
    setAuthUser(session.user);
    setCsrfToken(session.csrf_token);
    setAuthConfigurationError("");
    setAuthStatus("signed-in");
  };

  const signOut = async () => {
    setAuthActionError("");
    try {
      const response = await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrfToken },
      });
      if (!response.ok) {
        setAuthActionError(await getResponseError(response));
        return;
      }
      setAuthUser(null);
      setCsrfToken("");
      setAuthStatus("signed-out");
    } catch (error) {
      setAuthActionError(
        error instanceof Error ? error.message : "Sign out could not be completed."
      );
    }
  };

  const createUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setUserManagementError("");
    setUserManagementMessage("");
    setCreatingUser(true);
    try {
      const response = await fetch("/api/v1/auth/users", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ email: newUserEmail, password: newUserPassword }),
      });
      if (!response.ok) throw new Error(await getResponseError(response));
      const account = (await response.json()) as AuthUser;
      setUserManagementMessage(`Account created for ${account.email}.`);
      setNewUserEmail("");
      setNewUserPassword("");
    } catch (error) {
      setUserManagementError(
        error instanceof Error ? error.message : "The account could not be created."
      );
    } finally {
      setCreatingUser(false);
    }
  };

  const toggleAlertStatus = useCallback((alertId: string) => {
    setAlertStatuses((prev) => {
      const current = prev[alertId] || "open";
      const next: "open" | "acknowledged" | "resolved" =
        current === "open" ? "acknowledged" : current === "acknowledged" ? "resolved" : "open";
      const updated = { ...prev, [alertId]: next };
      try {
        localStorage.setItem("medipredict_alert_statuses", JSON.stringify(updated));
      } catch {
        // storage fallback
      }
      return updated;
    });
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    const requests = await Promise.allSettled([
      fetchApi<{ status: string }>("health"),
      fetchApi<Summary>("inventory/summary"),
      fetchApi<RiskRecord[]>("predictions/risk-register?limit=5000"),
      fetchApi<StockAlert[]>("alerts"),
      fetchApi<TransferCandidate[]>("transfers/recommendations"),
      fetchApi<TrustMetrics>("analytics/trust-metrics"),
    ]);

    const messages: string[] = [];
    const [healthRes, summaryRes, riskRes, alertRes, transferRes, metricsRes] = requests;

    setApiConnected(healthRes.status === "fulfilled" && healthRes.value.status === "ok");
    if (healthRes.status === "rejected") {
      messages.push(`API Health: ${healthRes.reason instanceof Error ? healthRes.reason.message : "Service unavailable"}`);
    } else if (healthRes.value.status !== "ok") {
      messages.push("API Health: service did not return an OK status");
    }

    if (summaryRes.status === "fulfilled") {
      setSummary(summaryRes.value);
    } else {
      setSummary(null);
      messages.push(`Summary: ${summaryRes.reason instanceof Error ? summaryRes.reason.message : "Failed to load summary"}`);
    }

    if (riskRes.status === "fulfilled") {
      setRisks(riskRes.value);
    } else {
      setRisks([]);
      messages.push(`Risk Register: ${riskRes.reason instanceof Error ? riskRes.reason.message : "Failed to load register"}`);
    }

    if (alertRes.status === "fulfilled") {
      setAlerts(alertRes.value);
    } else {
      setAlerts([]);
      messages.push(`Alerts: ${alertRes.reason instanceof Error ? alertRes.reason.message : "Failed to load alerts"}`);
    }

    if (transferRes.status === "fulfilled") {
      setTransfers(transferRes.value);
    } else {
      setTransfers([]);
      messages.push(`Transfers: ${transferRes.reason instanceof Error ? transferRes.reason.message : "Failed to load transfers"}`);
    }

    if (metricsRes.status === "fulfilled") {
      setMetrics(metricsRes.value);
    } else {
      setMetrics(null);
      messages.push(`Model Metrics: ${metricsRes.reason instanceof Error ? metricsRes.reason.message : "Failed to load metrics"}`);
    }

    setErrors(messages);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (authStatus === "signed-in") void loadData();
  }, [authStatus, loadData]);

  // Handle CSV assessment
  const submitUpload = async (file?: File) => {
    if (!file) return;
    setUploadError("");
    setUpload(null);

    if (!file.name.toLowerCase().endsWith(".csv")) {
      setUploadError("Please choose a valid .csv file.");
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      setUploadError("The CSV file must be under 20 MB.");
      return;
    }

    setUploading(true);
    const body = new FormData();
    body.append("file", file);

    try {
      const response = await fetch("/api/v1/data/assess-csv", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrfToken },
        body,
      });
      if (!response.ok) throw new Error(await getResponseError(response));
      setUpload((await response.json()) as UploadResult);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload could not be completed.");
    } finally {
      setUploading(false);
    }
  };

  // Filtered risks for RiskRegisterView
  const filteredRisks = useMemo(() => {
    return risks.filter((item) => {
      const matchesRisk =
        riskFilter === "All risk levels" ||
        item.risk_level.toLowerCase() === riskFilter.toLowerCase();
      const needle = riskQuery.trim().toLowerCase();
      const matchesQuery =
        !needle ||
        `${item.facility} ${item.district} ${item.medicine} ${item.medicine_code}`
          .toLowerCase()
          .includes(needle);
      return matchesRisk && matchesQuery;
    });
  }, [risks, riskQuery, riskFilter]);

  const activeNav = navItems.find((item) => item.id === view);
  const latestReportingDate = summary?.reporting_date && summary.reporting_date !== "—"
    ? summary.reporting_date
    : "Date unavailable";

  if (authStatus === "checking") {
    return <main className="auth-page"><p className="auth-loading">Checking secure session…</p></main>;
  }
  if (authStatus === "signed-out") {
    return (
      <LoginView
        configurationError={authConfigurationError}
        onLogin={signIn}
      />
    );
  }

  return (
    <div className="app-shell">
      {/* Mobile Header Bar */}
      <div className="mobile-header">
        <button
          type="button"
          className="mobile-menu-toggle"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          aria-label="Toggle navigation menu"
        >
          <Icon name={mobileMenuOpen ? "close" : "grid"} size={22} />
        </button>
        <div className="mobile-brand">
          <strong>MediPredict</strong> Rwanda
        </div>
        <div className={`mobile-status-dot ${apiConnected ? "online" : "offline"}`} />
      </div>

      {/* Sidebar Navigation */}
      <aside className={`sidebar ${mobileMenuOpen ? "mobile-open" : ""}`}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setView("overview");
            setMobileMenuOpen(false);
          }}
        >
          <div className="brand-mark">
            <span className="brand-cross-h" />
            <span className="brand-cross-v" />
            <span className="brand-center-dot" />
          </div>
          <div className="brand-text">
            <span>medi<strong>predict</strong></span>
            <small>RWANDA HEALTH INTELLIGENCE</small>
          </div>
        </a>

        <div className="workspace-label">SUPPLY CHAIN WORKSPACE</div>

        <nav className="main-nav" aria-label="Main Navigation">
          {navItems.map((item) => {
            const count = item.badgeCount ? item.badgeCount(alerts, transfers) : null;
            const isActive = view === item.id;
            return (
              <button
                key={item.id}
                type="button"
                className={`nav-link ${isActive ? "active" : ""}`}
                onClick={() => {
                  setView(item.id);
                  setMobileMenuOpen(false);
                }}
                aria-current={isActive ? "page" : undefined}
              >
                <Icon name={item.icon} size={18} />
                <span className="nav-label">{item.label}</span>
                {count !== null && <span className="nav-count-badge">{count}</span>}
              </button>
            );
          })}
        </nav>

        <div className="sidebar-bottom">
          <div className="status-card" role="status" aria-live="polite">
            <span className={`status-indicator-dot ${loading ? "loading" : apiConnected ? "online" : "offline"}`} />
            <div className="status-info">
              <strong>{loading ? "Checking API…" : apiConnected ? "API Connected" : "API Offline"}</strong>
              <small>{apiConnected ? "Backend health check passed" : "Backend health check failed"}</small>
            </div>
          </div>

          <div className="user-profile-card">
            <div className="profile-avatar">RW</div>
            <div className="profile-details">
              <strong>{authUser?.email}</strong>
              <small>{authUser?.role === "admin" ? "Administrator" : "Workspace user"}</small>
            </div>
          </div>
          {authActionError && <p className="auth-inline-error" role="alert">{authActionError}</p>}
          <div className="account-actions">
            {authUser?.role === "admin" && (
              <button
                type="button"
                className="account-action"
                onClick={() => {
                  setUserManagementOpen(true);
                  setUserManagementError("");
                  setUserManagementMessage("");
                }}
              >
                Create user
              </button>
            )}
            <button type="button" className="account-action" onClick={() => void signOut()}>
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="main-area">
        {/* Top Header Bar */}
        <header className="topbar">
          <div className="breadcrumb-trail">
            <span className="crumb-root">MediPredict</span>
            <Icon name="chevron" size={13} />
            <strong className="crumb-active">{activeNav?.label}</strong>
          </div>

          <div className="topbar-actions">
            <div className="snapshot-indicator" title="Latest reported inventory period in current dataset">
              <span className="live-dot" />
              <span>Snapshot: <strong>{latestReportingDate}</strong></span>
            </div>

            <button
              type="button"
              className="refresh-btn"
              onClick={() => void loadData()}
              disabled={loading}
              title="Refresh inventory and risk data from backend"
            >
              <Icon name="refresh" size={15} className={loading ? "spin-icon" : ""} />
              <span>{loading ? "Refreshing…" : "Refresh Data"}</span>
            </button>
          </div>
        </header>

        {/* Page Inner Content */}
        <div className="page-content">
          {/* Global dashboard availability errors */}
          {errors.length > 0 && (
            <div className="global-error-banner" role="alert">
              <Icon name="alert-triangle" size={20} />
              <div className="error-body">
                <strong>
                  {apiConnected
                    ? "The API is running, but some dashboard data is unavailable:"
                    : "The backend API could not be reached:"}
                </strong>
                <p>{errors.join(" · ")}</p>
                <small>
                  {apiConnected
                    ? "Check the backend logs and storage configuration. For Cloudflare R2, confirm the dashboard object key matches an existing CSV in the configured bucket."
                    : "Check that the backend service is running and that the frontend is configured to reach its API URL."}
                </small>
              </div>
              <button
                type="button"
                className="retry-btn"
                onClick={() => void loadData()}
                disabled={loading}
              >
                <Icon name="refresh" size={14} />
                <span>Retry</span>
              </button>
            </div>
          )}

          {/* Demonstration Data and Limitations Banner */}
          <div className="data-integrity-notice">
            <div className="integrity-icon">
              <Icon name="shield" size={18} />
            </div>
            <div className="integrity-text">
              <strong>Demonstration &amp; Methodology Disclosure:</strong>
              <span>
                Inventory, consumption, and risk predictions are synthetic demonstration data.
                District indicators are unverified seed values.
                Model serving is not enabled; risk classifications use rule-based days-of-cover logic.
                Do not use outputs for clinical or procurement decisions.
              </span>
            </div>
            <button
              type="button"
              className="integrity-link-btn"
              onClick={() => setView("trust")}
            >
              <span>Methodology &amp; Governance</span>
              <Icon name="arrow-right" size={13} />
            </button>
          </div>

          {/* Active View Rendering */}
          {view === "overview" && (
            <OverviewView
              summary={summary}
              risks={risks}
              alerts={alerts}
              transfers={transfers}
              loading={loading}
              onNavigate={(dest) => setView(dest as View)}
              onInspectMedicine={(med) => setSelectedMedicine(med)}
              alertStatuses={alertStatuses}
            />
          )}

          {view === "inventory" && (
            <InventoryView
              risks={risks}
              loading={loading}
              onInspectMedicine={(med) => setSelectedMedicine(med)}
            />
          )}

          {view === "alerts" && (
            <AlertsView
              alerts={alerts}
              risks={risks}
              loading={loading}
              alertStatuses={alertStatuses}
              onToggleStatus={toggleAlertStatus}
              onInspectMedicine={(med) => setSelectedMedicine(med)}
              onNavigateToTransfers={() => setView("transfers")}
            />
          )}

          {view === "risk" && (
            <RiskRegisterView
              rows={filteredRisks}
              query={riskQuery}
              setQuery={setRiskQuery}
              riskFilter={riskFilter}
              setRiskFilter={setRiskFilter}
              loading={loading}
              onInspectMedicine={(med) => setSelectedMedicine(med)}
            />
          )}

          {view === "transfers" && (
            <TransfersView
              rows={transfers}
              loading={loading}
            />
          )}

          {view === "trust" && (
            <TrustView
              metrics={metrics}
              loading={loading}
            />
          )}

          {view === "upload" && (
            <UploadView
              result={upload}
              error={uploadError}
              uploading={uploading}
              onSelect={submitUpload}
            />
          )}

          {/* Page Footer */}
          <footer className="page-footer">
            <div className="footer-left">
              <strong>MediPredict Rwanda</strong>
              <span className="footer-sep">·</span>
              <span>Essential Medicine Availability &amp; Stockout Prevention</span>
            </div>
            <div className="footer-right">
              <span>Demonstration &amp; Evaluation Environment</span>
              <span className="footer-sep">·</span>
              <span>Rule-Based Cover Analysis</span>
            </div>
          </footer>
        </div>
      </main>

      {/* Global Medicine Detail Inspection Modal */}
      {selectedMedicine && (() => {
        const matchingAlert = alerts.find(
          (a) =>
            a.facility.toLowerCase() === selectedMedicine.facility.toLowerCase() &&
            a.medicine_code.toLowerCase() === selectedMedicine.medicine_code.toLowerCase()
        );
        const alertId = matchingAlert
          ? matchingAlert.alert_id
          : `${selectedMedicine.facility.toLowerCase()}_${selectedMedicine.medicine_code.toLowerCase()}`;
        return (
          <MedicineDetailModal
            item={selectedMedicine}
            onClose={() => setSelectedMedicine(null)}
            transfers={transfers}
            onNavigateToTransfers={() => {
              setSelectedMedicine(null);
              setView("transfers");
            }}
            alertStatus={alertStatuses[alertId] || "open"}
            onToggleStatus={() => toggleAlertStatus(alertId)}
          />
        );
      })()}
      {userManagementOpen && authUser?.role === "admin" && (
        <div className="auth-modal-backdrop" role="presentation">
          <section
            className="auth-card user-management-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-user-title"
          >
            <button
              type="button"
              className="auth-modal-close"
              onClick={() => setUserManagementOpen(false)}
              aria-label="Close create user form"
            >
              ×
            </button>
            <p className="auth-eyebrow">ADMINISTRATOR ACCESS</p>
            <h2 id="create-user-title">Create workspace user</h2>
            <p className="auth-description">New accounts receive standard user access, not administrator privileges.</p>
            {userManagementError && <div className="auth-error" role="alert">{userManagementError}</div>}
            {userManagementMessage && <div className="auth-success" role="status">{userManagementMessage}</div>}
            <form className="auth-form" onSubmit={(event) => void createUser(event)}>
              <label htmlFor="new-user-email">Email address</label>
              <input
                id="new-user-email"
                type="email"
                required
                maxLength={254}
                value={newUserEmail}
                onChange={(event) => setNewUserEmail(event.target.value)}
              />
              <label htmlFor="new-user-password">Temporary password</label>
              <input
                id="new-user-password"
                type="password"
                required
                minLength={12}
                maxLength={256}
                autoComplete="new-password"
                value={newUserPassword}
                onChange={(event) => setNewUserPassword(event.target.value)}
              />
              <small className="auth-hint">Use at least 12 characters. Share it securely.</small>
              <button type="submit" className="auth-submit" disabled={creatingUser}>
                {creatingUser ? "Creating account…" : "Create user"}
              </button>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}

export default App;
