import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { CsvAssessmentItem, FeatureImportance, RiskRecord, StockAlert, Summary, TransferCandidate, TrustMetrics, UploadResult } from "./types";

type View = "overview" | "alerts" | "risk" | "transfers" | "trust" | "upload";
type IconName = "grid" | "pulse" | "truck" | "shield" | "upload" | "refresh" | "search" | "arrow" | "close" | "check" | "alert" | "file" | "chevron";

const navItems: { id: View; label: string; icon: IconName }[] = [
  { id: "overview", label: "Overview", icon: "grid" },
  { id: "alerts", label: "Stock alerts", icon: "alert" },
  { id: "risk", label: "Risk register", icon: "pulse" },
  { id: "transfers", label: "Stock transfers", icon: "truck" },
  { id: "trust", label: "Model insights", icon: "shield" },
  { id: "upload", label: "Upload data", icon: "upload" },
];

async function fetchApi<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1/${path}`);
  if (!response.ok) throw new Error(await getResponseError(response));
  return response.json() as Promise<T>;
}

function AlertsView({ alerts, loading }: { alerts: StockAlert[]; loading: boolean }) {
  return <section className="view-section">
    <div className="section-intro"><div><div className="eyebrow"><span className="eyebrow-line" />STOCK MONITORING</div><h1>Stock alerts<span className="heading-period">.</span></h1><p className="page-subtitle">Current reported stock-out, low-cover, and missing-consumption warnings.</p></div><span className="result-count">{formatNumber(alerts.length)} active alerts</span></div>
    <div className="notice-card"><span className="notice-icon"><Icon name="alert" size={18} /></span><div><strong>Stock availability estimates</strong><p>7- and 14-day remaining stock is estimated from current stock and reported average daily consumption, assuming a constant rate and no incoming receipts. This is a simple projection, not a trained forecast. Confirm stock, consumption, and expected deliveries before acting.</p></div></div>
    <div className="panel">
      {alerts.length ? <div className="table-wrap"><table className="full-table"><thead><tr><th>Priority</th><th>Facility / district</th><th>Medicine</th><th>Available</th><th>Daily use</th><th>After 7 days</th><th>After 14 days</th><th>Cover</th><th>Reported</th><th>Data</th></tr></thead><tbody>
        {alerts.map((alert) => <tr key={alert.alert_id}><td><span className={`risk-badge ${alert.severity}`}>{alert.alert_type.replaceAll("_", " ")}</span></td><td><strong>{alert.facility}</strong><span>{alert.district}</span></td><td><strong>{alert.medicine}</strong><span>{alert.medicine_code}</span></td><td>{formatNumber(alert.stock_units)} <small>units</small></td><td>{formatNumber(alert.daily_consumption)} <small>units/day</small></td><td>{formatNumber(alert.estimated_stock_after_7_days)} <small>units</small></td><td>{formatNumber(alert.estimated_stock_after_14_days)} <small>units</small></td><td>{formatDays(alert.lead_time_days)}</td><td>{alert.reporting_date}</td><td><span className={`assessment-badge ${alert.is_synthetic ? "synthetic-badge" : "source-badge"}`}>{alert.is_synthetic ? "Synthetic" : alert.data_source === "uploaded" ? "Uploaded" : "Real"}</span><span className="alert-message">{alert.message}</span></td></tr>)}
      </tbody></table></div> : <EmptyState>{loading ? "Loading stock alerts…" : "No active stock warnings in the latest reported snapshot."}</EmptyState>}
      <div className="table-bottom"><span>Alerts use the latest available row per facility and medicine.</span><span>Not a forecast</span></div>
    </div>
  </section>;
}

async function getResponseError(response: Response): Promise<string> {
  const body = await response.text();
  if (body) {
    try {
      const payload = JSON.parse(body) as { detail?: unknown; message?: unknown };
      if (typeof payload.detail === "string") return payload.detail;
      if (typeof payload.message === "string") return payload.message;
      if (Array.isArray(payload.detail)) {
        return payload.detail
          .map((item: unknown) => {
            if (typeof item === "object" && item !== null && "msg" in item) {
              return String(item.msg);
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

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
    pulse: <><path d="M3 12h4l3-8 4 16 3-8h4" /></>,
    truck: <><path d="M3 6h12v12H3z" /><path d="M15 10h4l3 3v5h-7z" /><circle cx="7.5" cy="19" r="1.5" /><circle cx="18.5" cy="19" r="1.5" /></>,
    shield: <><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11z" /><path d="m9 12 2 2 4-4" /></>,
    upload: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="m17 8-5-5-5 5M12 3v12" /></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M5.6 9a7 7 0 0 1 11.6-2L20 12M4 12l2.8 5a7 7 0 0 0 11.6-2" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
    arrow: <><path d="M7 17 17 7M7 7h10v10" /></>,
    close: <><path d="m18 6-12 12M6 6l12 12" /></>,
    check: <><path d="m5 12 4 4L19 6" /></>,
    alert: <><path d="m10.3 3.9-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3.1l-8-14a2 2 0 0 0-3.4 0z" /><path d="M12 9v4m0 4h.01" /></>,
    file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M8 13h8m-8 4h8" /></>,
    chevron: <><path d="m9 18 6-6-6-6" /></>,
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function RiskBadge({ risk }: { risk: string }) {
  const level = risk.toLowerCase();
  return <span className={`risk-badge ${level}`}>{risk.toLowerCase()}</span>;
}

function StatCard({ label, value, note, icon, tone }: { label: string; value: string; note: string; icon: IconName; tone: string }) {
  return <article className="stat-card">
    <div className={`stat-icon ${tone}`}><Icon name={icon} size={20} /></div>
    <p className="stat-label">{label}</p>
    <p className="stat-value">{value}</p>
    <p className="stat-note">{note}</p>
  </article>;
}

function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon name="file" size={21} /></span><p>{children}</p></div>;
}

function formatNumber(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? "—" : new Intl.NumberFormat().format(value);
}

function formatDays(value: number | null) {
  return value !== null && Number.isFinite(value) ? `${Math.round(value)} days` : "n/a";
}

function formatConfidence(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? "n/a" : `${(value * 100).toFixed(1)}%`;
}

function AssessmentBadges({ item }: { item: Pick<RiskRecord, "method" | "data_source" | "is_synthetic"> }) {
  return <span className="assessment-badges">
    {item.method === "rule_based_fallback" && <span className="assessment-badge method-badge" title="Rule-based days-of-cover estimate; this is not an AI prediction.">Rule-based estimate</span>}
    {item.data_source === "uploaded" && <span className="assessment-badge source-badge">Uploaded</span>}
    {item.is_synthetic && <span className="assessment-badge synthetic-badge">Synthetic</span>}
    {item.data_source === "real" && !item.is_synthetic && <span className="assessment-badge source-badge">Real</span>}
  </span>;
}

function readableFeature(feature: string) {
  return feature.replace(/^(numeric__|categorical__)/, "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function App() {
  const [view, setView] = useState<View>("overview");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [risks, setRisks] = useState<RiskRecord[]>([]);
  const [alerts, setAlerts] = useState<StockAlert[]>([]);
  const [transfers, setTransfers] = useState<TransferCandidate[]>([]);
  const [metrics, setMetrics] = useState<TrustMetrics | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [apiConnected, setApiConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [riskFilter, setRiskFilter] = useState("All risk levels");
  const [upload, setUpload] = useState<UploadResult | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [uploading, setUploading] = useState(false);

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
    const [healthResult, summaryResult, riskResult, alertResult, transferResult, metricsResult] = requests;
    setApiConnected(healthResult.status === "fulfilled" && healthResult.value.status === "ok");
    if (healthResult.status === "rejected") {
      messages.push(`API health: ${healthResult.reason instanceof Error ? healthResult.reason.message : "request failed"}`);
    } else if (healthResult.value.status !== "ok") {
      messages.push("API health: service did not report an OK status");
    }
    if (summaryResult.status === "fulfilled") setSummary(summaryResult.value);
    else {
      setSummary(null);
      messages.push(`Inventory summary: ${summaryResult.reason instanceof Error ? summaryResult.reason.message : "request failed"}`);
    }
    if (riskResult.status === "fulfilled") setRisks(riskResult.value);
    else {
      setRisks([]);
      messages.push(`Risk register: ${riskResult.reason instanceof Error ? riskResult.reason.message : "request failed"}`);
    }
    if (alertResult.status === "fulfilled") setAlerts(alertResult.value);
    else {
      setAlerts([]);
      messages.push(`Stock alerts: ${alertResult.reason instanceof Error ? alertResult.reason.message : "request failed"}`);
    }
    if (transferResult.status === "fulfilled") setTransfers(transferResult.value);
    else {
      setTransfers([]);
      messages.push(`Transfer recommendations: ${transferResult.reason instanceof Error ? transferResult.reason.message : "request failed"}`);
    }
    if (metricsResult.status === "fulfilled") setMetrics(metricsResult.value);
    else {
      setMetrics(null);
      messages.push(`Model insights: ${metricsResult.reason instanceof Error ? metricsResult.reason.message : "request failed"}`);
    }
    setErrors(messages);
    setLoading(false);
  }, []);

  useEffect(() => { void loadData(); }, [loadData]);

  const filteredRisks = useMemo(() => risks.filter((item) => {
    const matchesRisk = riskFilter === "All risk levels" || item.risk_level.toLowerCase() === riskFilter.toLowerCase();
    const needle = query.trim().toLowerCase();
    const matchesQuery = !needle || `${item.facility} ${item.district} ${item.medicine} ${item.medicine_code}`.toLowerCase().includes(needle);
    return matchesRisk && matchesQuery;
  }), [risks, query, riskFilter]);

  const submitUpload = async (file?: File) => {
    if (!file) return;
    setUploadError("");
    setUpload(null);
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setUploadError("Choose a .csv file.");
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      setUploadError("The CSV must be smaller than 20 MB.");
      return;
    }
    setUploading(true);
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch("/api/v1/data/assess-csv", { method: "POST", body });
      if (!response.ok) throw new Error(await getResponseError(response));
      setUpload(await response.json() as UploadResult);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "Upload could not be completed.");
    } finally {
      setUploading(false);
    }
  };

  const title = navItems.find((item) => item.id === view)?.label ?? "Overview";
  const latestDate = summary?.reporting_date && summary.reporting_date !== "—" ? summary.reporting_date : "Date unavailable";

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={(event) => { event.preventDefault(); setView("overview"); }}>
        <span className="brand-mark"><span /></span>
        <span className="brand-text">medi<span>predict</span><small>RWANDA HEALTH INTELLIGENCE</small></span>
      </a>
      <div className="workspace-label">WORKSPACE</div>
      <nav className="main-nav" aria-label="Main navigation">
        {navItems.map((item) => <button key={item.id} type="button" title={item.label} aria-label={item.label} aria-current={view === item.id ? "page" : undefined} className={`nav-link ${view === item.id ? "active" : ""}`} onClick={() => setView(item.id)}>
          <Icon name={item.icon} /><span>{item.label}</span>{item.id === "alerts" && alerts.length > 0 && <span className="nav-count">{formatNumber(alerts.length)}</span>}
        </button>)}
      </nav>
      <div className="sidebar-bottom">
        <div className="status-card" role="status" aria-live="polite"><span className={`status-dot ${!apiConnected && !loading ? "offline" : loading ? "loading" : "online"}`} /><div><strong>{loading ? "Checking connection" : apiConnected ? "API connected" : "API unavailable"}</strong><small>{apiConnected ? "MediPredict API" : "FastAPI service"}</small></div><span className={`status-ping ${!apiConnected && !loading ? "offline" : loading ? "loading" : ""}`} /></div>
        <div className="profile"><div className="profile-avatar">MP</div><div><strong>Health operations</strong><small>Rwanda workspace</small></div></div>
      </div>
    </aside>

    <main className="main-area">
      <header className="topbar">
        <div className="breadcrumb"><span>Workspace</span><Icon name="chevron" size={14} /><strong>{title}</strong></div>
        <div className="topbar-actions"><span className="reporting-date"><span className="live-dot" />Updated {latestDate}</span><button type="button" className="refresh-button" onClick={() => void loadData()} disabled={loading}><Icon name="refresh" size={16} /><span>{loading ? "Refreshing" : "Refresh data"}</span></button></div>
      </header>

      <div className="page-content">
        {errors.length > 0 && <div className="error-banner"><Icon name="alert" size={18} /><div><strong>Some dashboard data could not be loaded.</strong><p>{errors.join(" · ")}. Check that the API is running on port 8000, then retry.</p></div><button type="button" className="icon-button" aria-label="Retry loading dashboard data" title="Retry loading dashboard data" onClick={() => void loadData()} disabled={loading}><Icon name="refresh" size={17} /></button></div>}

        <div className="data-notice"><span className="notice-icon"><Icon name="alert" size={17} /></span><p><strong>Demonstration data</strong><span>Inventory, consumption, and risk predictions are synthetic. District indicators are unverified seed values. Do not use for operational decisions.</span></p><button type="button" onClick={() => setView("trust")}>Model limitations <Icon name="arrow" size={13} /></button></div>

        {view === "overview" && <Overview summary={summary} risks={risks} transfers={transfers} loading={loading} onNavigate={setView} />}
        {view === "alerts" && <AlertsView alerts={alerts} loading={loading} />}
        {view === "risk" && <RiskRegister rows={filteredRisks} query={query} setQuery={setQuery} riskFilter={riskFilter} setRiskFilter={setRiskFilter} loading={loading} />}
        {view === "transfers" && <TransferView rows={transfers} loading={loading} />}
        {view === "trust" && <TrustView metrics={metrics} loading={loading} />}
        {view === "upload" && <UploadView result={upload} error={uploadError} uploading={uploading} onSelect={submitUpload} />}

        <footer className="page-footer"><span>MediPredict Rwanda <span className="footer-separator">·</span> Medicine availability monitoring</span><span>For demonstration and evaluation only</span></footer>
      </div>
    </main>
  </div>;
}

function Overview({ summary, risks, transfers, loading, onNavigate }: { summary: Summary | null; risks: RiskRecord[]; transfers: TransferCandidate[]; loading: boolean; onNavigate: (view: View) => void }) {
  const priorityRows = [...risks].filter((item) => item.risk_level.toLowerCase() === "critical").sort((a, b) => (a.lead_time_days ?? 0) - (b.lead_time_days ?? 0)).slice(0, 5);
  const totalRisk = (summary?.critical ?? 0) + (summary?.moderate ?? 0) + (summary?.stable ?? 0) + (summary?.unknown ?? 0);
  const criticalPercent = totalRisk ? Math.round((summary!.critical / totalRisk) * 100) : 0;
  const moderatePercent = totalRisk ? Math.round((summary!.moderate / totalRisk) * 100) : 0;
  const stablePercent = totalRisk ? Math.round((summary!.stable / totalRisk) * 100) : 0;
  const unknownPercent = totalRisk ? Math.round((summary!.unknown / totalRisk) * 100) : 0;
  return <>
    <section className="welcome-row"><div><div className="eyebrow"><span className="eyebrow-line" />SUPPLY WATCH</div><h1>Good morning<span className="heading-period">.</span></h1><p className="page-subtitle">A clear view of medicine availability across Rwanda.</p></div><button type="button" className="primary-button" onClick={() => onNavigate("upload")}><Icon name="upload" size={16} /> Upload facility data</button></section>
    <section className="stat-grid">
      <StatCard label="Facilities monitored" value={summary ? formatNumber(summary.facilities) : loading ? "—" : "Unavailable"} note={`${formatNumber(summary?.districts)} districts represented`} icon="grid" tone="mint" />
      <StatCard label="Critical stock alerts" value={summary ? formatNumber(summary.critical) : loading ? "—" : "Unavailable"} note={`${formatNumber(summary?.moderate)} additional low-cover warnings`} icon="alert" tone="rose" />
      <StatCard label="Medicines tracked" value={summary ? formatNumber(summary.medicines) : loading ? "—" : "Unavailable"} note={`${formatNumber(summary?.stock_units)} total units reported`} icon="file" tone="blue" />
      <StatCard label="Transfer opportunities" value={formatNumber(transfers.length)} note="Suggested stock rebalancing" icon="truck" tone="amber" />
    </section>
    <section className="overview-grid">
      <article className="panel risk-panel">
        <div className="panel-heading"><div><div className="eyebrow small">ATTENTION REQUIRED</div><h2>Priority stock alerts</h2></div><button className="text-button" onClick={() => onNavigate("risk")}>View risk register <Icon name="arrow" size={14} /></button></div>
        {loading && !risks.length ? <div className="table-loading">Loading risk register…</div> : priorityRows.length ? <div className="table-wrap"><table><thead><tr><th>Facility &amp; district</th><th>Medicine</th><th>Cover</th><th>Risk</th></tr></thead><tbody>{priorityRows.map((row, index) => <tr key={`${row.facility}-${row.medicine_code}-${index}`}><td><strong>{row.facility}</strong><span>{row.district}</span></td><td>{row.medicine}<span>{row.medicine_code}</span></td><td><strong className="cover-critical">{formatDays(row.lead_time_days)}</strong></td><td><RiskBadge risk={row.risk_level} /><AssessmentBadges item={row} /></td></tr>)}</tbody></table></div> : <EmptyState>{loading ? "Loading priority alerts…" : "No critical alerts are currently available."}</EmptyState>}
        <div className="panel-footnote">Rule-based stock-cover tiers: Critical &lt;7 days, Moderate 7–14 days, Stable &gt;14 days. Unknown means consumption is unavailable. Verify alerts against source records.</div>
      </article>
      <article className="panel distribution-panel">
        <div className="panel-heading"><div><div className="eyebrow small">INVENTORY HEALTH</div><h2>Risk distribution</h2></div><span className="soft-tag">All records</span></div>
        <div className="distribution-total"><strong>{summary ? formatNumber(totalRisk) : "—"}</strong><span>facility–medicine records</span></div>
        <div className="stacked-bar" role="img" aria-label={`Risk distribution: ${summary?.critical ?? 0} critical, ${summary?.moderate ?? 0} moderate, ${summary?.stable ?? 0} stable, ${summary?.unknown ?? 0} with unavailable cover`}>
          <span className="segment critical-segment" style={{ width: `${totalRisk ? (summary!.critical / totalRisk) * 100 : 0}%` }} />
          <span className="segment moderate-segment" style={{ width: `${totalRisk ? (summary!.moderate / totalRisk) * 100 : 0}%` }} />
          <span className="segment stable-segment" style={{ width: `${totalRisk ? (summary!.stable / totalRisk) * 100 : 0}%` }} />
          <span className="segment unknown-segment" style={{ width: `${totalRisk ? (summary!.unknown / totalRisk) * 100 : 0}%` }} />
        </div>
        <div className="distribution-list">
          <DistributionItem label="Critical" count={summary?.critical} percent={criticalPercent} tone="critical" />
          <DistributionItem label="Moderate" count={summary?.moderate} percent={moderatePercent} tone="moderate" />
          <DistributionItem label="Stable" count={summary?.stable} percent={stablePercent} tone="stable" />
          <DistributionItem label="Cover unavailable" count={summary?.unknown} percent={unknownPercent} tone="unknown" />
        </div>
        <div className="distribution-foot"><span>Based on latest reporting period</span><span>{summary?.reporting_date ?? "—"}</span></div>
      </article>
    </section>
    <section className="insight-strip"><div className="insight-mark"><Icon name="truck" size={20} /></div><div><strong>Stock rebalancing opportunities</strong><p>{transfers.length ? `${formatNumber(transfers.length)} suggested transfers may help address low-cover facilities.` : "No transfer recommendations are currently available."}</p></div><button className="text-button" onClick={() => onNavigate("transfers")}>Explore transfers <Icon name="arrow" size={14} /></button></section>
  </>;
}

function DistributionItem({ label, count, percent, tone }: { label: string; count?: number; percent: number; tone: string }) {
  return <div className="distribution-item"><span className={`legend-dot ${tone}`} /><span className="distribution-label">{label}</span><strong>{formatNumber(count)}</strong><span className="distribution-percent">{percent}%</span></div>;
}

function RiskRegister({ rows, query, setQuery, riskFilter, setRiskFilter, loading }: { rows: RiskRecord[]; query: string; setQuery: (value: string) => void; riskFilter: string; setRiskFilter: (value: string) => void; loading: boolean }) {
  return <section className="view-section">
    <div className="section-intro"><div><div className="eyebrow"><span className="eyebrow-line" />MONITORING</div><h1>Risk register<span className="heading-period">.</span></h1><p className="page-subtitle">Review medicine availability signals by facility and district.</p></div><span className="result-count">{formatNumber(rows.length)} records</span></div>
    <div className="panel">
      <div className="table-toolbar"><label className="search-box"><Icon name="search" size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search facility, medicine, or district" /></label><select aria-label="Filter by risk level" value={riskFilter} onChange={(event) => setRiskFilter(event.target.value)}><option>All risk levels</option><option>Critical</option><option>Moderate</option><option>Stable</option><option>Unknown</option></select></div>
      <div className="table-wrap"><table className="full-table"><thead><tr><th>Facility</th><th>District</th><th>Medicine</th><th>Stock now</th><th>Daily use</th><th>After 7 days</th><th>After 14 days</th><th>Stock cover</th><th>Risk level</th><th>Confidence</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.facility}-${row.medicine_code}-${index}`}><td><strong>{row.facility}</strong><span>{row.province}</span></td><td>{row.district}</td><td><strong>{row.medicine}</strong><span>{row.medicine_code}</span></td><td>{formatNumber(row.stock_units)} <small>units</small></td><td>{formatNumber(row.daily_consumption)} <small>units</small></td><td>{formatNumber(row.estimated_stock_after_7_days)} <small>units</small></td><td>{formatNumber(row.estimated_stock_after_14_days)} <small>units</small></td><td>{formatDays(row.lead_time_days)}</td><td><RiskBadge risk={row.risk_level} /><AssessmentBadges item={row} /></td><td title={row.confidence_note}>{formatConfidence(row.confidence)}</td></tr>)}</tbody></table>
        {!rows.length && <EmptyState>{loading ? "Loading risk records…" : "No records match these filters."}</EmptyState>}</div>
      <div className="table-bottom"><span>Showing up to 5,000 records from the API.</span><span>Demonstration data only</span></div>
    </div>
  </section>;
}

function TransferView({ rows, loading }: { rows: TransferCandidate[]; loading: boolean }) {
  return <section className="view-section">
    <div className="section-intro"><div><div className="eyebrow"><span className="eyebrow-line" />STOCK OPTIMIZATION</div><h1>Stock transfers<span className="heading-period">.</span></h1><p className="page-subtitle">Suggested facility-to-facility rebalancing opportunities.</p></div><span className="result-count">{formatNumber(rows.length)} suggestions</span></div>
    <div className="transfer-grid">{rows.map((row, index) => <article className="panel transfer-card" key={`${row.donor_facility}-${row.recipient_facility}-${row.medicine}-${index}`}>
      <div className="transfer-card-top"><span className="medicine-chip">{row.medicine}</span><span className="transfer-units">{formatNumber(row.available_units)} <small>units</small></span></div>
      <div className="transfer-route"><div className="route-point"><span className="route-dot donor" /><div><small>DONOR FACILITY</small><strong>{row.donor_facility}</strong><span>{row.donor_district} · {formatDays(row.donor_lead_time_days)} cover</span></div></div><div className="route-line"><span><Icon name="arrow" size={13} /></span></div><div className="route-point"><span className="route-dot recipient" /><div><small>RECIPIENT FACILITY</small><strong>{row.recipient_facility}</strong><span>{row.recipient_district} · {formatDays(row.recipient_lead_time_days)} cover</span></div></div></div>
      <div className="transfer-card-bottom"><span><Icon name="alert" size={14} /> Suggested quantity</span><strong>{formatNumber(row.requested_units)} units</strong></div>
    </article>)}</div>
    {!rows.length && <div className="panel">{loading ? <div className="table-loading">Loading transfer recommendations…</div> : <EmptyState>No transfer recommendations are currently available.</EmptyState>}</div>}
    <p className="disclaimer-line"><Icon name="alert" size={15} /> Suggestions are generated from synthetic inventory values and require independent verification.</p>
  </section>;
}

function TrustView({ metrics, loading }: { metrics: TrustMetrics | null; loading: boolean }) {
  const metricsAvailable = metrics?.accuracy !== null && metrics?.accuracy !== undefined;
  const features = (metricsAvailable ? metrics?.feature_importances ?? [] : []).slice(0, 8);
  const maxImportance = Math.max(...features.map((feature) => feature.importance), 0);
  return <section className="view-section">
    <div className="section-intro"><div><div className="eyebrow"><span className="eyebrow-line" />MODEL TRANSPARENCY</div><h1>Model insights<span className="heading-period">.</span></h1><p className="page-subtitle">Understand the current model outputs and their limitations.</p></div><span className="soft-tag"><span className="live-dot" />Transparency</span></div>
    <div className="notice-card"><span className="notice-icon"><Icon name="alert" size={18} /></span><div><strong>No validated predictive model is available</strong><p>Current risk classifications use fixed days-of-cover rules. They are rule-based estimates, not AI predictions. Synthetic demonstration data and legacy metrics are not evidence of real-world performance.</p></div></div>
    <div className="trust-grid"><article className="panel accuracy-card"><div className="eyebrow small">VALIDATED MODEL METRIC</div><h2>Accuracy</h2><div className="accuracy-number">{metricsAvailable && metrics?.accuracy !== null ? <>{(metrics.accuracy * 100).toFixed(1)}<small>%</small></> : "—"}</div><p>{metricsAvailable ? "Metric from a model with accepted validation metadata." : "No validated model evaluation is available; legacy accuracy is withheld."}</p><div className="metric-source"><span>Evaluation source</span><strong>{metrics?.source ? metrics.source.split(/[\\/]/).pop() : loading ? "Loading…" : "Unavailable"}</strong></div></article>
      <article className="panel features-card"><div className="panel-heading"><div><div className="eyebrow small">MODEL SIGNALS</div><h2>Feature importance</h2></div><span className="soft-tag">Top {features.length}</span></div>{features.length ? <div className="feature-list">{features.map((feature: FeatureImportance) => <div className="feature-row" key={feature.feature}><div className="feature-label"><span>{readableFeature(feature.feature)}</span><strong>{(feature.importance * 100).toFixed(1)}%</strong></div><div className="feature-track"><span style={{ width: `${maxImportance ? (feature.importance / maxImportance) * 100 : 0}%` }} /></div></div>)}</div> : <EmptyState>{loading ? "Loading model metrics…" : "No feature importance data is available."}</EmptyState>}</article></div>
    {metricsAvailable && metrics?.labels.length ? <article className="panel class-metrics"><div className="eyebrow small">CLASS-LEVEL METRICS</div><h2>Precision &amp; recall</h2><div className="class-metric-grid">{metrics.labels.map((label, index) => <div className="class-metric" key={label}><RiskBadge risk={label} /><div><span>Precision</span><strong>{metrics.precision[index] === undefined ? "—" : `${(metrics.precision[index] * 100).toFixed(1)}%`}</strong></div><div><span>Recall</span><strong>{metrics.recall[index] === undefined ? "—" : `${(metrics.recall[index] * 100).toFixed(1)}%`}</strong></div></div>)}</div></article> : null}
  </section>;
}

function UploadView({ result, error, uploading, onSelect }: { result: UploadResult | null; error: string; uploading: boolean; onSelect: (file?: File) => void }) {
  const [fileName, setFileName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const handleFile = (file?: File) => {
    setFileName(file?.name ?? "");
    onSelect(file);
    if (inputRef.current) inputRef.current.value = "";
  };
  return <section className="view-section">
    <div className="section-intro"><div><div className="eyebrow"><span className="eyebrow-line" />DATA INTAKE</div><h1>Upload facility data<span className="heading-period">.</span></h1><p className="page-subtitle">Run a risk assessment on a facility inventory CSV.</p></div></div>
    <div className="upload-layout"><article className="panel upload-panel"><div className="upload-heading"><span className="upload-symbol"><Icon name="upload" size={23} /></span><div><h2>Assess daily inventory CSV</h2><p>Assessment is in-memory only; it does not save or train.</p></div></div><label className={`dropzone ${uploading ? "is-uploading" : ""}`}><input ref={inputRef} type="file" accept=".csv,text/csv" disabled={uploading} onChange={(event) => handleFile(event.target.files?.[0])} /><span className="drop-icon"><Icon name="file" size={25} /></span><strong>{uploading ? "Assessing file…" : fileName || "Choose a CSV file to assess"}</strong><span>{uploading ? "Please wait while the assessment is generated" : "Select a file from your computer · CSV format"}</span><span className="browse-button">{uploading ? "Working…" : "Browse files"}</span></label>{error && <div className="inline-error" role="alert"><Icon name="alert" size={16} />{error}</div>}<div className="required-fields"><strong>Required CSV columns</strong><p>facility_id, item_id, date (YYYY-MM-DD), stock_on_hand, units_consumed, units_received, is_synthetic (true or false)</p><strong>Optional columns</strong><p>stockout_flag, lead_time_days, reorder_level, facility_type, region</p></div></article>
      <aside className="upload-aside"><div className="eyebrow small">BEFORE YOU UPLOAD</div><ul><li><span><Icon name="check" size={14} /></span>Daily stock and movement quantities must be non-negative.</li><li><span><Icon name="check" size={14} /></span>State is_synthetic as true or false; unknown provenance is rejected.</li><li><span><Icon name="check" size={14} /></span>Assessment warns on short histories; training requires at least 90 records per pair and 12 pairs.</li><li><span><Icon name="check" size={14} /></span>Maximum file size is 20 MB; CSV only.</li></ul><div className="upload-note"><Icon name="alert" size={17} /><p>Assessment uses fixed days-of-cover rules. It is not a trained prediction, and no confidence probability is reported.</p></div></aside></div>
    {result && <article className="panel upload-results"><div className="panel-heading"><div><div className="eyebrow small">ASSESSMENT COMPLETE</div><h2>Assessment summary</h2></div><span className="success-tag"><Icon name="check" size={14} />Completed</span></div><div className="upload-stat-grid"><div><span>Records received</span><strong>{formatNumber(result.records_received)}</strong></div><div><span>Assessments generated</span><strong>{formatNumber(result.predictions)}</strong></div><div><span>Critical</span><strong className="text-critical">{formatNumber(result.critical)}</strong></div><div><span>Moderate</span><strong className="text-moderate">{formatNumber(result.moderate)}</strong></div><div><span>Stable</span><strong className="text-stable">{formatNumber(result.stable)}</strong></div></div>{result.validation.warnings.length > 0 && <div className="panel-footnote">Validation warnings: {formatNumber(result.validation.total_counts.returned_warnings)} shown of {formatNumber(result.validation.total_counts.warnings)} total.{result.validation.total_counts.warnings_truncated ? " Warning list is capped." : ""}</div>}{result.items.length > 0 && <><div className="table-wrap"><table><thead><tr><th>Facility / item</th><th>Date</th><th>Available stock</th><th>After 7 days</th><th>After 14 days</th><th>Estimated cover</th><th>Risk and method</th><th>Confidence</th></tr></thead><tbody>{result.items.slice(0, 8).map((item: CsvAssessmentItem, index) => <tr key={`${item.facility_id}-${item.item_id}-${index}`}><td>{item.facility_id}<span>{item.item_id}</span></td><td>{item.date}</td><td>{formatNumber(item.stock_on_hand)} <small>units</small></td><td>{formatNumber(item.estimated_stock_after_7_days)} <small>units</small></td><td>{formatNumber(item.estimated_stock_after_14_days)} <small>units</small></td><td>{formatDays(item.lead_time_days)}</td><td><RiskBadge risk={item.risk_level} /><AssessmentBadges item={item} /></td><td title={item.confidence_note}>{formatConfidence(item.confidence)}</td></tr>)}</tbody></table></div><div className="panel-footnote">Projections assume constant reported daily consumption and no incoming receipts. Showing {Math.min(result.items.length, 8)} of {formatNumber(result.predictions)} records. Rule-based estimates are not AI predictions.</div></>}</article>}
  </section>;
}

export default App;
