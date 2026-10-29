import { useState, useRef, type FormEvent } from "react";
import type { UploadResult, CsvAssessmentItem, DatasetDetail } from "../types";
import { Icon } from "../components/Icons";
import {
  RiskBadge,
  CoverBadge,
  ProvenanceBadge,
  ProvenanceStatusBadge,
  VerificationCard,
} from "../components/Badges";
import { ProjectionSparkline } from "../components/ProjectionSparkline";

interface UploadViewProps {
  result: UploadResult | null;
  error: string;
  uploading: boolean;
  onSelect: (file?: File) => void;
}

const REQUIRED_COLUMNS = [
  { name: "facility_id", type: "string", description: "Unique facility identifier (e.g. RW-KAY-HC01)" },
  { name: "item_id", type: "string", description: "Medicine or product code (e.g. AL-20120)" },
  { name: "date", type: "YYYY-MM-DD", description: "Reporting date in ISO format (e.g. 2026-03-01)" },
  { name: "stock_on_hand", type: "number", description: "Available stock units on hand (&ge; 0)" },
  { name: "units_consumed", type: "number", description: "Units dispensed/consumed during period (&ge; 0)" },
  { name: "units_received", type: "number", description: "Units received into inventory during period (&ge; 0)" },
];

const OPTIONAL_COLUMNS = [
  { name: "is_synthetic", type: "boolean", description: "Set true for synthetic records; if omitted, synthetic status is unknown" },
  { name: "stockout_flag", type: "boolean", description: "Explicit stockout indicator (true/false)" },
  { name: "lead_time_days", type: "number", description: "Supplier replenishment lead time in days" },
  { name: "reorder_level", type: "number", description: "Facility safety threshold for reordering" },
  { name: "facility_type", type: "string", description: "Hospital, Health Center, Health Post, Pharmacy" },
  { name: "region", type: "string", description: "Province or administrative region" },
];

function formatNum(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat().format(value);
}

export function UploadView({
  result,
  error,
  uploading,
  onSelect,
}: UploadViewProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileHeaders, setFileHeaders] = useState<string[]>([]);
  const [filePreviewRows, setFilePreviewRows] = useState<string[][]>([]);
  const [clientErrors, setClientErrors] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<"upload" | "specs">("upload");
  const [adminKey, setAdminKey] = useState("");
  const [datasets, setDatasets] = useState<DatasetDetail[]>([]);
  const [datasetLoading, setDatasetLoading] = useState(false);
  const [datasetError, setDatasetError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (file?: File) => {
    if (!file) return;

    setSelectedFile(file);
    setClientErrors([]);
    setFileHeaders([]);
    setFilePreviewRows([]);

    if (!file.name.toLowerCase().endsWith(".csv")) {
      setClientErrors(["Please select a file with the .csv extension."]);
      return;
    }

    if (file.size > 20 * 1024 * 1024) {
      setClientErrors(["File size exceeds the 20 MB maximum limit."]);
      return;
    }

    // Inspect first few lines on client side for immediate feedback
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      if (!text) return;

      const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
      if (lines.length > 0) {
        const headers = lines[0].split(",").map((h) => h.trim().replace(/^["']|["']$/g, ""));
        setFileHeaders(headers);

        const missingRequired = REQUIRED_COLUMNS.filter(
          (req) => !headers.some((h) => h.toLowerCase() === req.name.toLowerCase())
        );

        if (missingRequired.length > 0) {
          setClientErrors([
            `Missing required column(s): ${missingRequired.map((m) => m.name).join(", ")}.`,
          ]);
        }

        const previewRows = lines.slice(1, 6).map((line) =>
          line.split(",").map((val) => val.trim().replace(/^["']|["']$/g, ""))
        );
        setFilePreviewRows(previewRows);
      }
    };
    reader.readAsText(file.slice(0, 64 * 1024)); // Read first 64KB
  };

  const submitAssessment = () => {
    if (selectedFile) {
      onSelect(selectedFile);
    }
  };

  const loadDatasets = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setDatasetError("");
    setDatasetLoading(true);
    try {
      const response = await fetch("/api/v1/data/datasets", {
        headers: { "X-Admin-API-Key": adminKey },
      });
      if (!response.ok) {
        const body = await response.text();
        throw new Error(body || `Dataset request failed (${response.status}).`);
      }
      setDatasets((await response.json()) as DatasetDetail[]);
    } catch (loadError) {
      setDatasets([]);
      setDatasetError(
        loadError instanceof Error ? loadError.message : "Datasets could not be loaded."
      );
    } finally {
      setDatasetLoading(false);
    }
  };

  return (
    <div className="upload-view-container">
      {/* Header */}
      <section className="section-header">
        <div>
          <div className="eyebrow-pill">
            <span className="eyebrow-dot" />
            INVENTORY DATA INTAKE &amp; VALIDATION
          </div>
          <h1 className="page-title">
            Upload Facility Inventory CSV<span className="heading-period">.</span>
          </h1>
          <p className="page-subtitle">
          Validate and assess facility stock records in the backend, with accepted CSVs retained in configured storage.
          </p>
        </div>
        <div className="tabs-header-wrap">
          <button
            type="button"
            className={`tab-btn ${activeTab === "upload" ? "active" : ""}`}
            onClick={() => setActiveTab("upload")}
          >
            <Icon name="upload" size={14} />
            <span>Upload &amp; Assess</span>
          </button>
          <button
            type="button"
            className={`tab-btn ${activeTab === "specs" ? "active" : ""}`}
            onClick={() => setActiveTab("specs")}
          >
            <Icon name="file" size={14} />
            <span>CSV Specifications</span>
          </button>
        </div>
      </section>

      {/* Tab 1: Upload and Assessment Flow */}
      {activeTab === "upload" && (
        <>
          <div className="upload-layout-grid">
            {/* Left: Dropzone & Action Box */}
            <article className="panel upload-main-panel">
              <div className="panel-header">
                <div>
                  <div className="panel-eyebrow">FILE SELECTION</div>
                  <h2 className="panel-title">Select Inventory CSV File</h2>
                </div>
                <span className="tag-neutral">Max 20 MB</span>
              </div>

              {/* Drag and Drop Zone */}
              <label
                className={`csv-dropzone ${uploading ? "is-uploading" : ""} ${
                  selectedFile ? "has-file" : ""
                }`}
              >
                <input
                  ref={inputRef}
                  type="file"
                  accept=".csv,text/csv"
                  disabled={uploading}
                  onChange={(e) => handleFileChange(e.target.files?.[0])}
                  className="file-hidden-input"
                />
                <div className="dropzone-icon-box">
                  <Icon name={uploading ? "refresh" : selectedFile ? "check-circle" : "file"} size={32} className={uploading ? "spin-icon" : ""} />
                </div>
                <div className="dropzone-text">
                  <strong>
                    {uploading
                      ? "Assessing and storing facility records in the backend…"
                      : selectedFile
                      ? selectedFile.name
                      : "Drag & drop your inventory CSV here or click to browse"}
                  </strong>
                  <span>
                    {selectedFile
                      ? `${(selectedFile.size / 1024).toFixed(1)} KB · Ready to assess`
                      : "Supports daily or monthly facility stock files up to 20 MB"}
                  </span>
                </div>
                <span className="browse-pill-btn">
                  {uploading ? "Processing…" : selectedFile ? "Change file" : "Browse files"}
                </span>
              </label>

              {/* Client-side header check error */}
              {clientErrors.length > 0 && (
                <div className="client-error-banner" role="alert">
                  <Icon name="alert-triangle" size={16} />
                  <div>
                    <strong>Pre-flight validation warning:</strong>
                    <ul>
                      {clientErrors.map((err, idx) => (
                        <li key={idx}>{err}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}

              {/* Server-side error */}
              {error && (
                <div className="server-error-banner" role="alert">
                  <Icon name="alert-triangle" size={18} />
                  <div>
                    <strong>Upload failed:</strong>
                    <p>{error}</p>
                  </div>
                </div>
              )}

              {/* File header preview */}
              {selectedFile && fileHeaders.length > 0 && (
                <div className="file-preflight-box">
                  <div className="preflight-header">
                    <h4>Pre-flight Column Audit</h4>
                    <span className="preflight-tag">{fileHeaders.length} columns detected</span>
                  </div>
                  <div className="columns-chip-list">
                    {REQUIRED_COLUMNS.map((req) => {
                      const found = fileHeaders.some(
                        (h) => h.toLowerCase() === req.name.toLowerCase()
                      );
                      return (
                        <span
                          key={req.name}
                          className={`column-chip ${found ? "found" : "missing"}`}
                        >
                          <Icon name={found ? "check" : "close"} size={11} />
                          {req.name}
                        </span>
                      );
                    })}
                  </div>

                  {filePreviewRows.length > 0 && (
                    <div className="preview-table-wrap">
                      <table className="preview-data-table">
                        <thead>
                          <tr>
                            {fileHeaders.slice(0, 7).map((h, i) => (
                              <th key={i}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {filePreviewRows.map((row, rIdx) => (
                            <tr key={rIdx}>
                              {row.slice(0, 7).map((cell, cIdx) => (
                                <td key={cIdx}>{cell || "—"}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <span className="preview-table-note">
                        Showing first {filePreviewRows.length} rows preview before assessment
                      </span>
                    </div>
                  )}

                  {/* Submission action buttons */}
                  <div className="upload-actions-bar">
                    <button
                      type="button"
                      className="primary-action-button"
                      disabled={uploading || clientErrors.length > 0}
                      onClick={submitAssessment}
                    >
                      <Icon name="upload" size={16} />
                      <span>{uploading ? "Assessing Records…" : "Run In-Memory Risk Assessment"}</span>
                    </button>
                  </div>
                </div>
              )}
            </article>

            {/* Right: Validation & Assessment Guidelines */}
            <aside className="panel upload-guide-panel">
              <div className="panel-header">
                <div>
                  <div className="panel-eyebrow">PREPARATION CHECKLIST</div>
                  <h3 className="panel-title-sm">Before You Submit</h3>
                </div>
              </div>
              <ul className="checklist">
                <li>
                  <div className="check-bullet">
                    <Icon name="check" size={12} />
                  </div>
                  <div>
                    <strong>Non-negative numbers:</strong> Stock on hand, units consumed, and units received must be &ge; 0.
                  </div>
                </li>
                <li>
                  <div className="check-bullet">
                    <Icon name="check" size={12} />
                  </div>
                  <div>
                    <strong>Synthetic data:</strong> Set <code>is_synthetic=true</code> for synthetic records. If the column is omitted, the data is treated as uploaded with unknown synthetic status.
                  </div>
                </li>
                <li>
                  <div className="check-bullet">
                    <Icon name="check" size={12} />
                  </div>
                  <div>
                    <strong>Date formatting:</strong> Dates must use standard ISO format <code>YYYY-MM-DD</code>.
                  </div>
                </li>
                <li>
                  <div className="check-bullet">
                    <Icon name="check" size={12} />
                  </div>
                  <div>
                    <strong>In-memory processing:</strong> Uploaded CSV assessments are executed in-memory. They do not overwrite operational databases or train models.
                  </div>
                </li>
              </ul>

              <div className="upload-info-box">
                <Icon name="info" size={16} />
                <p>
                  <strong>Upload status:</strong> CSV files are labeled <code>Uploaded</code> based on how they enter the system.
                  Source verification is not required for in-memory assessment. Synthetic records remain labeled <code>Synthetic</code>.
                </p>
              </div>
            </aside>
          </div>

          <section className="panel registered-datasets-panel">
            <div className="panel-header">
              <div>
                <div className="panel-eyebrow">DATASET PROVENANCE</div>
                <h2 className="panel-title">Registered Uploads</h2>
                <p className="panel-description">
                  View provenance records for datasets stored by an administrator.
                </p>
              </div>
            </div>
            <form className="dataset-access-form" onSubmit={(event) => void loadDatasets(event)}>
              <label htmlFor="dataset-admin-key">Admin API key</label>
              <input
                id="dataset-admin-key"
                type="password"
                autoComplete="off"
                value={adminKey}
                onChange={(event) => setAdminKey(event.target.value)}
                required
              />
              <button type="submit" className="secondary-action-button" disabled={datasetLoading}>
                {datasetLoading ? "Loading…" : "Load registered uploads"}
              </button>
            </form>
            {datasetError && <p className="dataset-list-error" role="alert">{datasetError}</p>}
            {!datasetError && datasets.length === 0 && !datasetLoading && (
              <p className="dataset-list-empty">No registered uploads loaded.</p>
            )}
            {datasets.length > 0 && (
              <div className="registered-dataset-list">
                {datasets.map((dataset) => (
                  <article className="registered-dataset-card" key={dataset.dataset_id}>
                    <div className="registered-dataset-heading">
                      <strong>{dataset.dataset_id}</strong>
                      <ProvenanceStatusBadge status={dataset.provenance_status} />
                    </div>
                    <div className="registered-dataset-meta">
                      <span>Rows: {dataset.row_count ?? "n/a"}</span>
                      <span>Period: {dataset.date_range.start || "n/a"} to {dataset.date_range.end || "n/a"}</span>
                      <span>Uploader: {dataset.uploader?.trim() || "n/a"}</span>
                    </div>
                    {dataset.verification && (
                      <VerificationCard verification={dataset.verification} />
                    )}
                    {dataset.warning && (
                      <p className="dataset-list-warning" role="status">{dataset.warning}</p>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>

          {/* Assessment Results Section */}
          {result && (
            <section className="panel assessment-results-panel">
              <div className="panel-header">
                <div>
                  <div className="panel-eyebrow">EVALUATION COMPLETE</div>
                  <h2 className="panel-title">Assessment Summary &amp; Validation Report</h2>
                  <p className="panel-description">
                    Generated via rule-based days-of-cover logic on {formatNum(result.records_received)} uploaded records.
                  </p>
                </div>
                <span className="tag-success">
                  <Icon name="check-circle" size={14} />
                  Assessment Generated
                </span>
                <ProvenanceStatusBadge status={result.provenance_status} />
              </div>

              {/* Validation Counts Grid */}
              <div className="upload-results-stat-grid">
                <div className="result-stat-box">
                  <span className="stat-box-label">Records Processed</span>
                  <strong className="stat-box-val">{formatNum(result.records_received)}</strong>
                  <span className="stat-box-sub">Uploaded rows</span>
                </div>
                <div className="result-stat-box">
                  <span className="stat-box-label">Critical Risk</span>
                  <strong className="stat-box-val text-critical">{formatNum(result.critical)}</strong>
                  <span className="stat-box-sub">&lt;7 days cover</span>
                </div>
                <div className="result-stat-box">
                  <span className="stat-box-label">Moderate Risk</span>
                  <strong className="stat-box-val text-warning">{formatNum(result.moderate)}</strong>
                  <span className="stat-box-sub">7–14 days cover</span>
                </div>
                <div className="result-stat-box">
                  <span className="stat-box-label">Stable</span>
                  <strong className="stat-box-val text-stable">{formatNum(result.stable)}</strong>
                  <span className="stat-box-sub">&gt;14 days cover</span>
                </div>
                <div className="result-stat-box">
                  <span className="stat-box-label">Cover Unavailable</span>
                  <strong className="stat-box-val text-muted">{formatNum(result.unknown)}</strong>
                  <span className="stat-box-sub">Zero consumption</span>
                </div>
              </div>

              {/* Validation Warnings Table */}
              {result.validation && result.validation.warnings && result.validation.warnings.length > 0 && (
                <div className="validation-warnings-section">
                  <div className="warning-section-header">
                    <h4>Validation Notices ({result.validation.warnings.length})</h4>
                    <span className="warning-count-badge">Non-blocking warnings</span>
                  </div>
                  <div className="table-responsive">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Row #</th>
                          <th>Column</th>
                          <th>Code</th>
                          <th>Validation Message</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.validation.warnings.slice(0, 10).map((w, idx) => (
                          <tr key={idx}>
                            <td><strong>{w.row_number ?? "Header"}</strong></td>
                            <td><code>{w.column}</code></td>
                            <td><span className="code-pill">{w.code}</span></td>
                            <td>{w.message}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {result.validation.warnings.length > 10 && (
                    <span className="warnings-truncated-note">
                      Showing first 10 of {result.validation.warnings.length} total warnings.
                    </span>
                  )}
                </div>
              )}

              {/* Assessment Records Table */}
              {result.items && result.items.length > 0 && (
                <div className="assessment-items-section">
                  <div className="section-title-row">
                    <h4>Assessed Facility Medicine Items</h4>
                    <span className="section-subtitle">
                      Showing up to 10 records with 7d/14d stock trajectories
                    </span>
                  </div>
                  <div className="table-responsive">
                    <table className="data-table full-width">
                      <thead>
                        <tr>
                          <th>Facility &amp; Item</th>
                          <th>Reporting Date</th>
                          <th>Stock on Hand</th>
                          <th>Daily Consumption</th>
                          <th>Estimated Cover</th>
                          <th>Trajectory (14d)</th>
                          <th>Risk Tier</th>
                          <th>Data Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.items.slice(0, 10).map((item: CsvAssessmentItem, idx: number) => (
                          <tr key={`${item.facility_id}-${item.item_id}-${idx}`}>
                            <td>
                              <strong>{item.facility_id}</strong>
                              <span className="cell-sub">{item.item_id}</span>
                            </td>
                            <td>{item.date}</td>
                            <td>
                              <strong>{formatNum(item.stock_on_hand)}</strong> <span className="cell-unit">units</span>
                            </td>
                            <td>
                              <strong>{formatNum(item.units_consumed)}</strong> <span className="cell-unit">units/d</span>
                            </td>
                            <td>
                              <CoverBadge days={item.lead_time_days} />
                            </td>
                            <td>
                              <ProjectionSparkline
                                current={item.stock_on_hand}
                                after7Days={item.estimated_stock_after_7_days}
                                after14Days={item.estimated_stock_after_14_days}
                                label={`${item.facility_id} ${item.item_id}`}
                                compact
                              />
                            </td>
                            <td>
                              <RiskBadge risk={item.risk_level} />
                            </td>
                            <td>
                              <ProvenanceBadge
                                item={{
                                  method: "rule_based_fallback",
                                  data_source: "uploaded",
                                  is_synthetic: item.is_synthetic,
                                  provenance_status: item.provenance_status,
                                }}
                              />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="panel-footer-meta">
                    <span>
                      Projections assume constant consumption and no incoming deliveries. Showing first {Math.min(result.items.length, 10)} of {formatNum(result.predictions)} records.
                    </span>
                    <span>Source verification is optional for in-memory assessment.</span>
                  </div>
                </div>
              )}
            </section>
          )}
        </>
      )}

      {/* Tab 2: CSV Specifications & Column Schema */}
      {activeTab === "specs" && (
        <article className="panel specs-panel">
          <div className="panel-header">
            <div>
              <div className="panel-eyebrow">SCHEMA REFERENCE</div>
              <h2 className="panel-title">Required &amp; Optional CSV Columns</h2>
              <p className="panel-description">
                Format your CSV using the exact column headers below for automated schema validation and risk estimation.
              </p>
            </div>
          </div>

          <div className="specs-section">
            <h3 className="specs-heading">1. Mandatory Columns (Must be present in row 1)</h3>
            <div className="table-responsive">
              <table className="data-table full-width">
                <thead>
                  <tr>
                    <th>Column Name</th>
                    <th>Expected Data Type</th>
                    <th>Description &amp; Valid Values</th>
                  </tr>
                </thead>
                <tbody>
                  {REQUIRED_COLUMNS.map((col) => (
                    <tr key={col.name}>
                      <td><code>{col.name}</code></td>
                      <td><span className="type-badge">{col.type}</span></td>
                      <td>{col.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="specs-section">
            <h3 className="specs-heading">2. Optional Provenance &amp; Enrichment Columns</h3>
            <div className="table-responsive">
              <table className="data-table full-width">
                <thead>
                  <tr>
                    <th>Column Name</th>
                    <th>Expected Data Type</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {OPTIONAL_COLUMNS.map((col) => (
                    <tr key={col.name}>
                      <td><code>{col.name}</code></td>
                      <td><span className="type-badge">{col.type}</span></td>
                      <td>{col.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="specs-example-box">
            <h4>Sample CSV Format</h4>
            <pre className="csv-snippet">
{`facility_id,item_id,date,stock_on_hand,units_consumed,units_received,is_synthetic
RW-KAY-HC01,AL-20120,2026-03-01,150,25,0,false
RW-GAS-DH02,PARACET-500,2026-03-01,0,40,0,false
RW-NYA-HP03,AMOX-250,2026-03-01,420,18,100,false`}
            </pre>
          </div>
        </article>
      )}
    </div>
  );
}
