import { useState, useMemo } from "react";
import type { RiskRecord } from "../types";
import { Icon } from "../components/Icons";
import { RiskBadge, CoverBadge, ProvenanceBadge } from "../components/Badges";
import { ProjectionSparkline } from "../components/ProjectionSparkline";
import { EmptyState } from "../components/EmptyState";

interface InventoryViewProps {
  risks: RiskRecord[];
  loading: boolean;
  onInspectMedicine: (item: RiskRecord) => void;
}

type SortField = "medicine" | "facility" | "stock" | "consumption" | "cover" | "risk";
type SortDirection = "asc" | "desc";

function formatNum(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat().format(value);
}

export function InventoryView({
  risks,
  loading,
  onInspectMedicine,
}: InventoryViewProps) {
  const [search, setSearch] = useState("");
  const [districtFilter, setDistrictFilter] = useState("all");
  const [riskFilter, setRiskFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [provenanceFilter, setProvenanceFilter] = useState("all");
  const [sortField, setSortField] = useState<SortField>("cover");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  // Extract unique districts for dropdown
  const districts = useMemo(() => {
    const set = new Set<string>();
    risks.forEach((r) => {
      if (r.district) set.add(r.district);
    });
    return Array.from(set).sort();
  }, [risks]);

  // Filter records
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();

    return risks.filter((r) => {
      // Search
      if (q) {
        const hay = `${r.medicine} ${r.medicine_code} ${r.facility} ${r.district} ${r.province}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }

      // District
      if (districtFilter !== "all" && r.district.toLowerCase() !== districtFilter.toLowerCase()) {
        return false;
      }

      // Risk level
      if (riskFilter !== "all" && r.risk_level.toLowerCase() !== riskFilter.toLowerCase()) {
        return false;
      }

      // Stock status
      if (statusFilter === "stockout" && r.stock_units > 0) return false;
      if (statusFilter === "critical" && (r.lead_time_days === null || r.lead_time_days >= 7)) return false;
      if (statusFilter === "moderate" && (r.lead_time_days === null || r.lead_time_days < 7 || r.lead_time_days > 14)) return false;
      if (statusFilter === "stable" && (r.lead_time_days === null || r.lead_time_days <= 14)) return false;
      if (statusFilter === "missing_consumption" && r.daily_consumption > 0 && r.lead_time_days !== null) return false;

      // Provenance
      if (provenanceFilter === "synthetic" && !r.is_synthetic) return false;
      if (provenanceFilter === "real" && (r.is_synthetic || r.data_source === "uploaded")) return false;
      if (provenanceFilter === "uploaded" && r.data_source !== "uploaded") return false;

      return true;
    });
  }, [risks, search, districtFilter, riskFilter, statusFilter, provenanceFilter]);

  // Sort records
  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "medicine":
          cmp = a.medicine.localeCompare(b.medicine);
          break;
        case "facility":
          cmp = a.facility.localeCompare(b.facility);
          break;
        case "stock":
          cmp = a.stock_units - b.stock_units;
          break;
        case "consumption":
          cmp = a.daily_consumption - b.daily_consumption;
          break;
        case "cover": {
          const valA = a.lead_time_days ?? Infinity;
          const valB = b.lead_time_days ?? Infinity;
          cmp = valA - valB;
          break;
        }
        case "risk": {
          const rank: Record<string, number> = { critical: 0, moderate: 1, stable: 2, unknown: 3 };
          cmp = (rank[a.risk_level.toLowerCase()] ?? 4) - (rank[b.risk_level.toLowerCase()] ?? 4);
          break;
        }
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });
  }, [filtered, sortField, sortDirection]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const paginatedRows = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return sorted.slice(start, start + pageSize);
  }, [sorted, currentPage, pageSize]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDirection("asc");
    }
  };

  const resetFilters = () => {
    setSearch("");
    setDistrictFilter("all");
    setRiskFilter("all");
    setStatusFilter("all");
    setProvenanceFilter("all");
    setCurrentPage(1);
  };

  const hasActiveFilters =
    search.trim() !== "" ||
    districtFilter !== "all" ||
    riskFilter !== "all" ||
    statusFilter !== "all" ||
    provenanceFilter !== "all";

  return (
    <div className="inventory-view-container">
      {/* Intro Header */}
      <section className="section-header">
        <div>
          <div className="eyebrow-pill">
            <span className="eyebrow-dot" />
            MEDICINE INVENTORY CATALOG
          </div>
          <h1 className="page-title">
            Facility Inventory Register<span className="heading-period">.</span>
          </h1>
          <p className="page-subtitle">
            Search, filter, and inspect physical stock balances and days-of-cover projections across all reporting health facilities.
          </p>
        </div>
        <div className="header-meta-badge">
          <span className="meta-count">{formatNum(filtered.length)}</span>
          <span className="meta-label">records match filters</span>
        </div>
      </section>

      {/* Main Table Container */}
      <div className="panel table-panel">
        {/* Toolbar & Filters */}
        <div className="inventory-toolbar">
          <div className="search-input-wrap">
            <Icon name="search" size={16} />
            <input
              type="text"
              className="search-input"
              placeholder="Search by medicine name, code, facility, or district…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setCurrentPage(1);
              }}
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
            {/* District dropdown */}
            <div className="filter-select-wrap">
              <label htmlFor="inv-filter-district" className="filter-label">District:</label>
              <select
                id="inv-filter-district"
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

            {/* Risk Level dropdown */}
            <div className="filter-select-wrap">
              <label htmlFor="inv-filter-risk" className="filter-label">Risk Level:</label>
              <select
                id="inv-filter-risk"
                value={riskFilter}
                onChange={(e) => {
                  setRiskFilter(e.target.value);
                  setCurrentPage(1);
                }}
              >
                <option value="all">All Risk Tiers</option>
                <option value="critical">Critical (&lt; 7 days)</option>
                <option value="moderate">Moderate (7–14 days)</option>
                <option value="stable">Stable (&gt; 14 days)</option>
                <option value="unknown">Unknown / Unavailable</option>
              </select>
            </div>

            {/* Stock status filter */}
            <div className="filter-select-wrap">
              <label htmlFor="inv-filter-status" className="filter-label">Status:</label>
              <select
                id="inv-filter-status"
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  setCurrentPage(1);
                }}
              >
                <option value="all">All Statuses</option>
                <option value="stockout">Out of Stock (0 units)</option>
                <option value="critical">Critical Cover (&lt; 7d)</option>
                <option value="moderate">Moderate Cover (7-14d)</option>
                <option value="stable">Adequate Cover (&gt; 14d)</option>
                <option value="missing_consumption">Missing Consumption</option>
              </select>
            </div>

            {/* Provenance dropdown */}
            <div className="filter-select-wrap">
              <label htmlFor="inv-filter-provenance" className="filter-label">Data Origin:</label>
              <select
                id="inv-filter-provenance"
                value={provenanceFilter}
                onChange={(e) => {
                  setProvenanceFilter(e.target.value);
                  setCurrentPage(1);
                }}
              >
                <option value="all">All Origins</option>
                <option value="real">Non-synthetic data only</option>
                <option value="synthetic">Synthetic Demonstration</option>
                <option value="uploaded">Uploaded CSV</option>
              </select>
            </div>

            {hasActiveFilters && (
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

        {/* Table View */}
        {loading && !risks.length ? (
          <div className="table-loading-state">
            <Icon name="refresh" size={24} className="spin-icon" />
            <p>Loading facility inventory records…</p>
          </div>
        ) : paginatedRows.length > 0 ? (
          <div className="table-responsive">
            <table className="data-table full-width">
              <thead>
                <tr>
                  <th onClick={() => handleSort("medicine")} className="sortable-th">
                    <div className="th-content">
                      <span>Medicine &amp; Code</span>
                      <Icon
                        name={sortField === "medicine" && sortDirection === "desc" ? "chevron" : "chevron"}
                        size={12}
                        className={sortField === "medicine" ? "active-sort" : "sort-dim"}
                      />
                    </div>
                  </th>
                  <th onClick={() => handleSort("facility")} className="sortable-th">
                    <div className="th-content">
                      <span>Facility &amp; District</span>
                      <Icon
                        name="chevron"
                        size={12}
                        className={sortField === "facility" ? "active-sort" : "sort-dim"}
                      />
                    </div>
                  </th>
                  <th onClick={() => handleSort("stock")} className="sortable-th">
                    <div className="th-content">
                      <span>Stock on Hand</span>
                      <Icon
                        name="chevron"
                        size={12}
                        className={sortField === "stock" ? "active-sort" : "sort-dim"}
                      />
                    </div>
                  </th>
                  <th onClick={() => handleSort("consumption")} className="sortable-th">
                    <div className="th-content">
                      <span>Daily Use</span>
                      <Icon
                        name="chevron"
                        size={12}
                        className={sortField === "consumption" ? "active-sort" : "sort-dim"}
                      />
                    </div>
                  </th>
                  <th onClick={() => handleSort("cover")} className="sortable-th">
                    <div className="th-content">
                      <span>Days of Cover</span>
                      <Icon
                        name="chevron"
                        size={12}
                        className={sortField === "cover" ? "active-sort" : "sort-dim"}
                      />
                    </div>
                  </th>
                  <th>
                    <span>Trajectory (14d)</span>
                  </th>
                  <th onClick={() => handleSort("risk")} className="sortable-th">
                    <div className="th-content">
                      <span>Risk Tier</span>
                      <Icon
                        name="chevron"
                        size={12}
                        className={sortField === "risk" ? "active-sort" : "sort-dim"}
                      />
                    </div>
                  </th>
                  <th>
                    <span>Provenance</span>
                  </th>
                  <th>
                    <span>Action</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {paginatedRows.map((row, index) => {
                  const isStockout = row.stock_units <= 0;
                  const isCritical = row.lead_time_days !== null && row.lead_time_days < 7;

                  return (
                    <tr
                      key={`${row.facility}-${row.medicine_code}-${index}`}
                      className={isStockout ? "row-stockout" : isCritical ? "row-critical" : ""}
                    >
                      <td>
                        <strong className="medicine-name-cell">{row.medicine}</strong>
                        <span className="code-pill">{row.medicine_code}</span>
                      </td>
                      <td>
                        <strong>{row.facility}</strong>
                        <span className="cell-sub">{row.district}, {row.province}</span>
                      </td>
                      <td>
                        <span className={isStockout ? "text-critical font-bold" : "text-strong"}>
                          {formatNum(row.stock_units)}
                        </span>
                        <span className="cell-unit">units</span>
                      </td>
                      <td>
                        <span className={row.daily_consumption <= 0 ? "text-muted" : "text-strong"}>
                          {formatNum(row.daily_consumption)}
                        </span>
                        <span className="cell-unit">units/d</span>
                      </td>
                      <td>
                        <CoverBadge days={row.lead_time_days} />
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
                        <RiskBadge risk={row.risk_level} />
                      </td>
                      <td>
                        <ProvenanceBadge item={row} />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="inspect-btn primary-inspect"
                          onClick={() => onInspectMedicine(row)}
                          title="Open full medicine audit details"
                        >
                          <Icon name="eye" size={13} />
                          <span>Inspect</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No Matching Inventory Records"
            icon="search"
            actionText="Reset All Filters"
            onAction={resetFilters}
          >
            No facility inventory items matched your active search and filter criteria. Try broadening your query.
          </EmptyState>
        )}

        {/* Pagination Bar */}
        <div className="table-pagination">
          <div className="pagination-info">
            <span>
              Showing {sorted.length === 0 ? 0 : (currentPage - 1) * pageSize + 1} to{" "}
              {Math.min(currentPage * pageSize, sorted.length)} of {formatNum(sorted.length)} items
            </span>
            <div className="page-size-selector">
              <label htmlFor="page-size-select">Per page:</label>
              <select
                id="page-size-select"
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
