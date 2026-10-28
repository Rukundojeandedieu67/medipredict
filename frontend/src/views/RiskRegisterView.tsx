import { useState, useMemo } from "react";
import type { RiskRecord } from "../types";
import { Icon } from "../components/Icons";
import { RiskBadge, CoverBadge, ProvenanceBadge } from "../components/Badges";
import { ProjectionSparkline } from "../components/ProjectionSparkline";
import { EmptyState } from "../components/EmptyState";

interface RiskRegisterViewProps {
  rows: RiskRecord[];
  query: string;
  setQuery: (q: string) => void;
  riskFilter: string;
  setRiskFilter: (f: string) => void;
  loading: boolean;
  onInspectMedicine: (item: RiskRecord) => void;
}

function formatNum(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat().format(value);
}

export function RiskRegisterView({
  rows,
  query,
  setQuery,
  riskFilter,
  setRiskFilter,
  loading,
  onInspectMedicine,
}: RiskRegisterViewProps) {
  const [districtFilter, setDistrictFilter] = useState("all");
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const districts = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => {
      if (r.district) set.add(r.district);
    });
    return Array.from(set).sort();
  }, [rows]);

  const filteredRows = useMemo(() => {
    return rows.filter((r) => {
      if (districtFilter !== "all" && r.district.toLowerCase() !== districtFilter.toLowerCase()) {
        return false;
      }
      return true;
    });
  }, [rows, districtFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  const paginatedRows = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredRows.slice(start, start + pageSize);
  }, [filteredRows, currentPage, pageSize]);

  return (
    <div className="risk-register-view-container">
      {/* Header */}
      <section className="section-header">
        <div>
          <div className="eyebrow-pill">
            <span className="eyebrow-dot" />
            RISK ASSESSMENT REGISTER
          </div>
          <h1 className="page-title">
            Medicine Risk Register<span className="heading-period">.</span>
          </h1>
          <p className="page-subtitle">
            Comprehensive medicine risk classifications calculated via days-of-cover fallback logic.
          </p>
        </div>
        <div className="header-meta-badge">
          <span className="meta-count">{formatNum(filteredRows.length)}</span>
          <span className="meta-label">evaluated records</span>
        </div>
      </section>

      {/* Panel */}
      <div className="panel table-panel">
        <div className="inventory-toolbar">
          <div className="search-input-wrap">
            <Icon name="search" size={16} />
            <input
              type="text"
              className="search-input"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setCurrentPage(1);
              }}
              placeholder="Search facility, medicine, code, or district…"
            />
            {query && (
              <button
                type="button"
                className="clear-search-btn"
                onClick={() => setQuery("")}
                aria-label="Clear search"
              >
                <Icon name="close" size={14} />
              </button>
            )}
          </div>

          <div className="filters-group">
            <div className="filter-select-wrap">
              <label htmlFor="risk-reg-district" className="filter-label">District:</label>
              <select
                id="risk-reg-district"
                value={districtFilter}
                onChange={(e) => {
                  setDistrictFilter(e.target.value);
                  setCurrentPage(1);
                }}
              >
                <option value="all">All Districts ({districts.length})</option>
                {districts.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </div>

            <div className="filter-select-wrap">
              <label htmlFor="risk-reg-level" className="filter-label">Risk Level:</label>
              <select
                id="risk-reg-level"
                value={riskFilter}
                onChange={(e) => {
                  setRiskFilter(e.target.value);
                  setCurrentPage(1);
                }}
              >
                <option>All risk levels</option>
                <option>Critical</option>
                <option>Moderate</option>
                <option>Stable</option>
                <option>Unknown</option>
              </select>
            </div>
          </div>
        </div>

        {loading && !rows.length ? (
          <div className="table-loading-state">
            <Icon name="refresh" size={24} className="spin-icon" />
            <p>Loading risk assessment register…</p>
          </div>
        ) : paginatedRows.length > 0 ? (
          <div className="table-responsive">
            <table className="data-table full-width">
              <thead>
                <tr>
                  <th>Facility &amp; Province</th>
                  <th>District</th>
                  <th>Medicine &amp; Code</th>
                  <th>Stock on Hand</th>
                  <th>Daily Consumption</th>
                  <th>Stock Projection (14d)</th>
                  <th>Days of Cover</th>
                  <th>Risk Tier</th>
                  <th>Confidence &amp; Method</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {paginatedRows.map((row, index) => (
                  <tr key={`${row.facility}-${row.medicine_code}-${index}`}>
                    <td>
                      <strong>{row.facility}</strong>
                      <span className="cell-sub">{row.province} Province</span>
                    </td>
                    <td>{row.district}</td>
                    <td>
                      <strong>{row.medicine}</strong>
                      <span className="code-pill">{row.medicine_code}</span>
                    </td>
                    <td>
                      <strong>{formatNum(row.stock_units)}</strong>
                      <span className="cell-unit">units</span>
                    </td>
                    <td>
                      <strong>{formatNum(row.daily_consumption)}</strong>
                      <span className="cell-unit">units/d</span>
                    </td>
                    <td>
                      <ProjectionSparkline
                        current={row.stock_units}
                        after7Days={row.estimated_stock_after_7_days}
                        after14Days={row.estimated_stock_after_14_days}
                        label={`${row.facility} ${row.medicine}`}
                        compact
                      />
                    </td>
                    <td>
                      <CoverBadge days={row.lead_time_days} />
                    </td>
                    <td>
                      <RiskBadge risk={row.risk_level} />
                    </td>
                    <td>
                      <ProvenanceBadge item={row} />
                      <span className="confidence-caption" title={row.confidence_note}>
                        Rule-based threshold
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="inspect-btn"
                        onClick={() => onInspectMedicine(row)}
                        title="View detailed breakdown"
                      >
                        <Icon name="eye" size={13} />
                        <span>Inspect</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No Risk Records Found"
            icon="search"
            actionText="Clear Search"
            onAction={() => {
              setQuery("");
              setDistrictFilter("all");
              setRiskFilter("All risk levels");
            }}
          >
            No records matched your search filters.
          </EmptyState>
        )}

        {/* Pagination Bar */}
        <div className="table-pagination">
          <div className="pagination-info">
            <span>
              Showing {filteredRows.length === 0 ? 0 : (currentPage - 1) * pageSize + 1} to{" "}
              {Math.min(currentPage * pageSize, filteredRows.length)} of {formatNum(filteredRows.length)} items
            </span>
            <div className="page-size-selector">
              <label htmlFor="risk-page-size">Per page:</label>
              <select
                id="risk-page-size"
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setCurrentPage(1);
                }}
              >
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>
          </div>

          <div className="pagination-controls">
            <button
              type="button"
              className="pagination-btn"
              disabled={currentPage <= 1}
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              aria-label="Previous page"
            >
              Previous
            </button>
            <span className="page-indicator">
              Page <strong>{currentPage}</strong> of <strong>{totalPages}</strong>
            </span>
            <button
              type="button"
              className="pagination-btn"
              disabled={currentPage >= totalPages}
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              aria-label="Next page"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
