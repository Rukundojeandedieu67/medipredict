import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { FeatureImportance, RiskRecord, Summary, TransferCandidate, TrustMetrics, UploadResult } from "./types";

type View = "overview" | "risk" | "transfers" | "trust" | "upload";
type IconName = "grid" | "pulse" | "truck" | "shield" | "upload" | "refresh" | "search" | "arrow" | "close" | "check" | "alert" | "file" | "chevron";

const navItems: { id: View; label: string; icon: IconName }[] = [
  { id: "overview", label: "Overview", icon: "grid" },
  { id: "risk", label: "Risk register", icon: "pulse" },
  { id: "transfers", label: "Stock transfers", icon: "truck" },
  { id: "trust", label: "Model insights", icon: "shield" },
  { id: "upload", label: "Upload data", icon: "upload" },
];

async function fetchApi<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1/${path}`);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
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

function formatNumber(value: number | undefined) {
  return value === undefined || !Number.isFinite(value) ? "—" : new Intl.NumberFormat().format(value);
}

function formatDays(value: number) {
  return Number.isFinite(value) ? `${Math.round(value)} days` : "—";
}

function readableFeature(feature: string) {
  return feature.replace(/^(numeric__|categorical__)/, "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function App() {
  const [view, setView] = useState<View>("overview");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [risks, setRisks] = useState<RiskRecord[]>([]);
  const [transfers, setTransfers] = useState<TransferCandidate[]>([]);
  const [metrics, setMetrics] = useState<TrustMetrics | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [riskFilter, setRiskFilter] = useState("All risk levels");
  const [upload, setUpload] = useState<UploadResult | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [uploading, setUploading] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    const requests = await Promise.allSettled([
      fetchApi<Summary>("inventory/summary"),
      fetchApi<RiskRecord[]>("predictions/risk-register?limit=5000"),
      fetchApi<TransferCandidate[]>("transfers/recommendations"),
      fetchApi<TrustMetrics>("analytics/trust-metrics"),
    ]);
    const messages: string[] = [];
    const [summaryResult, riskResult, transferResult, metricsResult] = requests;
    if (summaryResult.status === "fulfilled") setSummary(summaryResult.value);
    else messages.push(`Inventory summary: ${summaryResult.reason instanceof Error ? summaryResult.reason.message : "request failed"}`);
    if (riskResult.status === "fulfilled") setRisks(riskResult.value);
    else messages.push(`Risk register: ${riskResult.reason instanceof Error ? riskResult.reason.message : "request failed"}`);
    if (transferResult.status === "fulfilled") setTransfers(transferResult.value);
    else messages.push(`Transfer recommendations: ${transferResult.reason instanceof Error ? transferResult.reason.message : "request failed"}`);
    if (metricsResult.status === "fulfilled") setMetrics(metricsResult.value);
    else messages.push(`Model insights: ${metricsResult.reason instanceof Error ? metricsResult.reason.message : "request failed"}`);
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
    setUploading(true);
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch("/api/v1/data/upload-csv", { method: "POST", body });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Upload failed (${response.status})`);
      }
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
        {navItems.map((item) => <button key={item.id} type="button" className={`nav-link ${view === item.id ? "active" : ""}`} onClick={() => setView(item.id)}>
          <Icon name={item.icon} /><span>{item.label}</span>{item.id === "risk" && summary && <span className="nav-count">{formatNumber(summary.critical)}</span>}
        </button>)}
      </nav>
      <div className="sidebar-bottom">
        <div className="status-card"><span className={`status-dot ${errors.length ? "offline" : loading ? "loading" : "online"}`} /><div><strong>{errors.length ? "Connection issue" : loading ? "Connecting" : "API connected"}</strong><small>{errors.length ? "Some data unavailable" : "MediPredict API"}</small></div><span className="status-ping" /></div>
        <div className="profile"><div className="profile-avatar">MP</div><div><strong>Health operations</strong><small>Rwanda workspace</small></div><button className="icon-button profile-menu" title="Workspace options"><span>•••</span></button></div>
      </div>
    </aside>

    <main className="main-area">
      <header className="topbar">
        <div className="breadcrumb"><span>Workspace</span><Icon name="chevron" size={14} /><strong>{title}</strong></div>
        <div className="topbar-actions"><span className="reporting-date"><span className="live-dot" />Updated {latestDate}</span><button type="button" className="refresh-button" onClick={() => void loadData()} disabled={loading}><Icon name="refresh" size={16} /><span>{loading ? "Refreshing" : "Refresh data"}</span></button></div>
      </header>

      <div className="page-content">
        {errors.length > 0 && <div className="error-banner"><Icon name="alert" size={18} /><div><strong>Some dashboard data could not be loaded.</strong><p>{errors.join(" · ")}. Check that the API is running on port 8000, then refresh.</p></div><button className="icon-button" aria-label="Dismiss errors" onClick={() => setErrors([])}><Icon name="close" size={17} /></button></div>}

        <div className="data-notice"><span className="notice-icon"><Icon name="alert" size={17} /></span><p><strong>Demonstration data</strong><span>Inventory, consumption, and risk predictions are synthetic. District indicators are unverified seed values. Do not use for operational decisions.</span></p><button type="button" onClick={() => setView("trust")}>Model limitations <Icon name="arrow" size={13} /></button></div>

        {view === "overview" && <Overview summary={summary} risks={risks} transfers={transfers} loading={loading} onNavigate={setView} />}
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
  const priorityRows = [...risks].filter((item) => item.risk_level.toLowerCase() === "critical").sort((a, b) => a.lead_time_days - b.lead_time_days).slice(0, 5);
  const totalRisk = (summary?.critical ?? 0) + (summary?.moderate ?? 0) + (summary?.stable ?? 0);
  const criticalPercent = totalRisk ? Math.round((summary!.critical / totalRisk) * 100) : 0;
  const moderatePercent = totalRisk ? Math.round((summary!.moderate / totalRisk) * 100) : 0;
  return <>
    <section className="welcome-row"><div><div className="eyebrow"><span className="eyebrow-line" />SUPPLY WATCH</div><h1>Good morning<span className="heading-period">.</span></h1><p className="page-subtitle">A clear view of medicine availability across Rwanda.</p></div><button type="button" className="primary-button" onClick={() => onNavigate("upload")}><Icon name="upload" size={16} /> Upload facility data</button></section>
    <section className="stat-grid">
      <StatCard label="Facilities monitored" value={summary ? formatNumber(summary.facilities) : loading ? "—" : "Unavailable"} note={`${formatNumber(summary?.districts)} districts represented`} icon="grid" tone="mint" />
      <StatCard label="Critical stock alerts" value={summary ? formatNumber(summary.critical) : loading ? "—" : "Unavailable"} note="Facilities requiring attention" icon="alert" tone="rose" />
      <StatCard label="Medicines tracked" value={summary ? formatNumber(summary.medicines) : loading ? "—" : "Unavailable"} note={`${formatNumber(summary?.stock_units)} total units reported`} icon="file" tone="blue" />
      <StatCard label="Transfer opportunities" value={formatNumber(transfers.length)} note="Suggested stock rebalancing" icon="truck" tone="amber" />
    </section>
    <section className="overview-grid">
      <article className="panel risk-panel">
        <div className="panel-heading"><div><div className="eyebrow small">ATTENTION REQUIRED</div><h2>Priority stock alerts</h2></div><button className="text-button" onClick={() => onNavigate("risk")}>View risk register <Icon name="arrow" size={14} /></button></div>
        {loading && !risks.length ? <div className="table-loading">Loading risk register…</div> : priorityRows.length ? <div className="table-wrap"><table><thead><tr><th>Facility &amp; district</th><th>Medicine</th><th>Cover</th><th>Risk</th></tr></thead><tbody>{priorityRows.map((row, index) => <tr key={`${row.facility}-${row.medicine_code}-${index}`}><td><strong>{row.facility}</strong><span>{row.district}</span></td><td>{row.medicine}<span>{row.medicine_code}</span></td><td><strong className="cover-critical">{formatDays(row.lead_time_days)}</strong></td><td><RiskBadge risk={row.risk_level} /></td></tr>)}</tbody></table></div> : <EmptyState>{loading ? "Loading priority alerts…" : "No critical alerts are currently available."}</EmptyState>}
        <div className="panel-footnote">Risk classifications shown are generated from synthetic demonstration data.</div>
      </article>
      <article className="panel distribution-panel">
        <div className="panel-heading"><div><div className="eyebrow small">INVENTORY HEALTH</div><h2>Risk distribution</h2></div><span className="soft-tag">All records</span></div>
        <div className="distribution-total"><strong>{summary ? formatNumber(totalRisk) : "—"}</strong><span>facility–medicine records</span></div>
        <div className="stacked-bar" role="img" aria-label={`Risk distribution: ${summary?.critical ?? 0} critical, ${summary?.moderate ?? 0} moderate, ${summary?.stable ?? 0} stable`}>
          <span className="segment critical-segment" style={{ width: `${totalRisk ? (summary!.critical / totalRisk) * 100 : 0}%` }} />
          <span className="segment moderate-segment" style={{ width: `${totalRisk ? (summary!.moderate / totalRisk) * 100 : 0}%` }} />
          <span className="segment stable-segment" style={{ width: `${totalRisk ? (summary!.stable / totalRisk) * 100 : 0}%` }} />
        </div>
        <div className="distribution-list">
          <DistributionItem label="Critical" count={summary?.critical} percent={criticalPercent} tone="critical" />
          <DistributionItem label="Moderate" count={summary?.moderate} percent={moderatePercent} tone="moderate" />
          <DistributionItem label="Stable" count={summary?.stable} percent={summary ? Math.max(0, 100 - criticalPercent - moderatePercent) : 0} tone="stable" />
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
      <div className="table-toolbar"><label className="search-box"><Icon name="search" size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search facility, medicine, or district" /></label><select aria-label="Filter by risk level" value={riskFilter} onChange={(event) => setRiskFilter(event.target.value)}><option>All risk levels</option><option>Critical</option><option>Moderate</option><option>Stable</option></select></div>
      <div className="table-wrap"><table className="full-table"><thead><tr><th>Facility</th><th>District</th><th>Medicine</th><th>Stock</th><th>Daily use</th><th>Stock cover</th><th>Risk level</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.facility}-${row.medicine_code}-${index}`}><td><strong>{row.facility}</strong><span>{row.province}</span></td><td>{row.district}</td><td><strong>{row.medicine}</strong><span>{row.medicine_code}</span></td><td>{formatNumber(row.stock_units)} <small>units</small></td><td>{formatNumber(row.daily_consumption)} <small>units</small></td><td>{formatDays(row.lead_time_days)}</td><td><RiskBadge risk={row.risk_level} /></td></tr>)}</tbody></table>
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
  const features = (metrics?.feature_importances ?? []).slice(0, 8);
  const maxImportance = Math.max(...features.map((feature) => feature.importance), 0);
  return <section className="view-section">
    <div className="section-intro"><div><div className="eyebrow"><span className="eyebrow-line" />MODEL TRANSPARENCY</div><h1>Model insights<span className="heading-period">.</span></h1><p className="page-subtitle">Understand the current model outputs and their limitations.</p></div><span className="soft-tag"><span className="live-dot" />Transparency</span></div>
    <div className="notice-card"><span className="notice-icon"><Icon name="alert" size={18} /></span><div><strong>Interpret metrics with caution</strong><p>The training data contains synthetic stock and consumption trajectories. Risk labels are derived from those values, so reported metrics are not evidence of real-world predictive performance.</p></div></div>
    <div className="trust-grid"><article className="panel accuracy-card"><div className="eyebrow small">REPORTED MODEL METRIC</div><h2>Accuracy</h2><div className="accuracy-number">{metrics ? `${(metrics.accuracy * 100).toFixed(1)}<small>%</small>` : "—"}</div><p>Stored training evaluation metric. It should not be interpreted as verified operational performance.</p><div className="metric-source"><span>Evaluation source</span><strong>{metrics?.source ? metrics.source.split(/[\\/]/).pop() : loading ? "Loading…" : "Unavailable"}</strong></div></article>
      <article className="panel features-card"><div className="panel-heading"><div><div className="eyebrow small">MODEL SIGNALS</div><h2>Feature importance</h2></div><span className="soft-tag">Top {features.length}</span></div>{features.length ? <div className="feature-list">{features.map((feature: FeatureImportance) => <div className="feature-row" key={feature.feature}><div className="feature-label"><span>{readableFeature(feature.feature)}</span><strong>{(feature.importance * 100).toFixed(1)}%</strong></div><div className="feature-track"><span style={{ width: `${maxImportance ? (feature.importance / maxImportance) * 100 : 0}%` }} /></div></div>)}</div> : <EmptyState>{loading ? "Loading model metrics…" : "No feature importance data is available."}</EmptyState>}</article></div>
    {metrics?.labels.length ? <article className="panel class-metrics"><div className="eyebrow small">CLASS-LEVEL METRICS</div><h2>Precision &amp; recall</h2><div className="class-metric-grid">{metrics.labels.map((label, index) => <div className="class-metric" key={label}><RiskBadge risk={label} /><div><span>Precision</span><strong>{metrics.precision[index] === undefined ? "—" : `${(metrics.precision[index] * 100).toFixed(1)}%`}</strong></div><div><span>Recall</span><strong>{metrics.recall[index] === undefined ? "—" : `${(metrics.recall[index] * 100).toFixed(1)}%`}</strong></div></div>)}</div></article> : null}
  </section>;
}

function UploadView({ result, error, uploading, onSelect }: { result: UploadResult | null; error: string; uploading: boolean; onSelect: (file?: File) => void }) {
  const [fileName, setFileName] = useState("");
  const handleFile = (file?: File) => { setFileName(file?.name ?? ""); onSelect(file); };
  return <section className="view-section">
    <div className="section-intro"><div><div className="eyebrow"><span className="eyebrow-line" />DATA INTAKE</div><h1>Upload facility data<span className="heading-period">.</span></h1><p className="page-subtitle">Run a risk assessment on a facility inventory CSV.</p></div></div>
    <div className="upload-layout"><article className="panel upload-panel"><div className="upload-heading"><span className="upload-symbol"><Icon name="upload" size={23} /></span><div><h2>Import a CSV file</h2><p>Your file is processed for predictions and is not saved by the API.</p></div></div><label className={`dropzone ${uploading ? "is-uploading" : ""}`}><input type="file" accept=".csv,text/csv" disabled={uploading} onChange={(event) => handleFile(event.target.files?.[0])} /><span className="drop-icon"><Icon name="file" size={25} /></span><strong>{uploading ? "Analyzing file…" : fileName || "Choose a CSV file to upload"}</strong><span>{uploading ? "Please wait while predictions are generated" : "Select a file from your computer · CSV format"}</span><span className="browse-button">{uploading ? "Working…" : "Browse files"}</span></label>{error && <div className="inline-error"><Icon name="alert" size={16} />{error}</div>}<div className="required-fields"><strong>Required CSV columns</strong><p>facility_name, district, province, facility_type, medicine_code, medicine_name, end_of_month_stock_units, avg_daily_consumption_units, nisr_under_5_population, nisr_poverty_rate_pct, nisr_malaria_prevalence_pct, rainy_season_active, reporting_month</p></div></article>
      <aside className="upload-aside"><div className="eyebrow small">BEFORE YOU UPLOAD</div><ul><li><span><Icon name="check" size={14} /></span>Use the required column names listed here.</li><li><span><Icon name="check" size={14} /></span>Maximum file size is 20 MB.</li><li><span><Icon name="check" size={14} /></span>Only CSV files are accepted.</li></ul><div className="upload-note"><Icon name="alert" size={17} /><p>Uploaded data is evaluated using the current demonstration model. Outputs are synthetic and must not guide real-world supply decisions.</p></div></aside></div>
    {result && <article className="panel upload-results"><div className="panel-heading"><div><div className="eyebrow small">ANALYSIS COMPLETE</div><h2>Prediction summary</h2></div><span className="success-tag"><Icon name="check" size={14} />Completed</span></div><div className="upload-stat-grid"><div><span>Records received</span><strong>{formatNumber(result.records_received)}</strong></div><div><span>Predictions generated</span><strong>{formatNumber(result.predictions)}</strong></div><div><span>Critical</span><strong className="text-critical">{formatNumber(result.critical)}</strong></div><div><span>Moderate</span><strong className="text-moderate">{formatNumber(result.moderate)}</strong></div><div><span>Stable</span><strong className="text-stable">{formatNumber(result.stable)}</strong></div></div>{result.items.length > 0 && <div className="table-wrap"><table><thead><tr><th>Facility</th><th>Medicine</th><th>Stock cover</th><th>Risk</th></tr></thead><tbody>{result.items.slice(0, 8).map((item, index) => <tr key={`${item.facility}-${item.medicine_code}-${index}`}><td>{item.facility}<span>{item.district}</span></td><td>{item.medicine}</td><td>{formatDays(item.lead_time_days)}</td><td><RiskBadge risk={item.risk_level} /></td></tr>)}</tbody></table></div>}</article>}
  </section>;
}

export default App;
