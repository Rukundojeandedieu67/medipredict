import { useState, useMemo } from "react";
import type { TransferCandidate } from "../types";
import { Icon } from "../components/Icons";
import { ProvenanceStatusBadge } from "../components/Badges";
import { EmptyState } from "../components/EmptyState";

interface TransfersViewProps {
  rows: TransferCandidate[];
  loading: boolean;
}

function formatNum(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat().format(value);
}

function formatDays(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return `${Math.round(value)} days`;
}

export function TransfersView({ rows, loading }: TransfersViewProps) {
  const [search, setSearch] = useState("");
  const [districtFilter, setDistrictFilter] = useState("all");

  const districts = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => {
      if (r.donor_district) set.add(r.donor_district);
      if (r.recipient_district) set.add(r.recipient_district);
    });
    return Array.from(set).sort();
  }, [rows]);

  const filteredTransfers = useMemo(() => {
    const q = search.trim().toLowerCase();

    return rows.filter((r) => {
      if (q) {
        const hay = `${r.medicine} ${r.donor_facility} ${r.donor_district} ${r.recipient_facility} ${r.recipient_district}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }

      if (districtFilter !== "all") {
        const matches =
          r.donor_district.toLowerCase() === districtFilter.toLowerCase() ||
          r.recipient_district.toLowerCase() === districtFilter.toLowerCase();
        if (!matches) return false;
      }

      return true;
    });
  }, [rows, search, districtFilter]);

  return (
    <div className="transfers-view-container">
      {/* Header */}
      <section className="section-header">
        <div>
          <div className="eyebrow-pill">
            <span className="eyebrow-dot" />
            STOCK REBALANCING OPTIMIZATION
          </div>
          <h1 className="page-title">
            Inter-Facility Stock Transfers<span className="heading-period">.</span>
          </h1>
          <p className="page-subtitle">
            Algorithmically identified mutual-aid opportunities: rebalancing surplus inventory from overstocked facilities (&gt;30 days cover) to facilities facing stockouts (&lt;14 days cover).
          </p>
        </div>
        <div className="header-meta-badge">
          <span className="meta-count">{formatNum(filteredTransfers.length)}</span>
          <span className="meta-label">transfer opportunities</span>
        </div>
      </section>

      {/* Notice Banner */}
      <div className="notice-banner">
        <div className="notice-icon-box">
          <Icon name="info" size={18} />
        </div>
        <div className="notice-body">
          <strong>Mutual-aid transfer guidelines:</strong>
          <p>
            Suggestions are derived from reported stock and consumption balances. Donor facilities retain a minimum 30-day buffer.
            Before authorizing a physical transfer, check batch expiry dates, temperature control during transit, and documented requisition approvals.
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="panel transfers-filter-panel">
        <div className="inventory-toolbar">
          <div className="search-input-wrap">
            <Icon name="search" size={16} />
            <input
              type="text"
              className="search-input"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search medicine, donor facility, or recipient facility…"
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
            <div className="filter-select-wrap">
              <label htmlFor="transfers-district-filter" className="filter-label">District:</label>
              <select
                id="transfers-district-filter"
                value={districtFilter}
                onChange={(e) => setDistrictFilter(e.target.value)}
              >
                <option value="all">All Districts ({districts.length})</option>
                {districts.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Transfer Grid */}
        {loading && !rows.length ? (
          <div className="table-loading-state">
            <Icon name="refresh" size={24} className="spin-icon" />
            <p>Evaluating stock rebalancing candidates…</p>
          </div>
        ) : filteredTransfers.length > 0 ? (
          <div className="transfer-cards-grid">
            {filteredTransfers.map((item, index) => (
              <article
                key={`${item.donor_facility}-${item.recipient_facility}-${item.medicine}-${index}`}
                className="panel transfer-item-card"
              >
                <div className="transfer-card-header">
                  <span className="medicine-tag">
                    <Icon name="package" size={13} />
                    {item.medicine}
                  </span>
                  <div className="transfer-qty-badge">
                    <span className="qty-val">{formatNum(item.requested_units)}</span>
                    <span className="qty-unit">units to transfer</span>
                  </div>
                </div>

                <div className="transfer-route-diagram">
                  {/* Donor */}
                  <div className="route-node donor-node">
                    <div className="node-marker donor-marker">
                      <Icon name="building" size={14} />
                    </div>
                    <div className="node-details">
                      <span className="node-role">DONOR FACILITY (SURPLUS)</span>
                      <strong className="node-name">{item.donor_facility}</strong>
                      <span className="node-sub">
                        {item.donor_district} · Buffer: <strong>{formatDays(item.donor_lead_time_days)}</strong>
                      </span>
                    </div>
                  </div>

                  {/* Route path */}
                  <div className="route-arrow-connector">
                    <div className="connector-line" />
                    <span className="connector-badge">
                      <Icon name="truck" size={14} />
                      Transfer Route
                    </span>
                    <div className="connector-line" />
                  </div>

                  {/* Recipient */}
                  <div className="route-node recipient-node">
                    <div className="node-marker recipient-marker">
                      <Icon name="building" size={14} />
                    </div>
                    <div className="node-details">
                      <span className="node-role text-critical">RECIPIENT FACILITY (DEFICIT)</span>
                      <strong className="node-name">{item.recipient_facility}</strong>
                      <span className="node-sub">
                        {item.recipient_district} · Buffer: <strong>{formatDays(item.recipient_lead_time_days)}</strong>
                      </span>
                    </div>
                  </div>
                </div>

                <div className="transfer-card-footer">
                  <div className="transfer-meta-note">
                    <Icon name="info" size={13} />
                    <span>Transfers preserve &ge; 30d cover at donor and restore &ge; 14d at recipient.</span>
                  </div>
                  <span className="transfer-provenance-pill">
                    <ProvenanceStatusBadge status={item.provenance_status} />
                  </span>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="No Transfer Suggestions Available"
            icon="truck"
            actionText="Clear Filters"
            onAction={() => {
              setSearch("");
              setDistrictFilter("all");
            }}
          >
            No candidate facilities meet the transfer criteria (donor with &gt;30d cover and recipient with &lt;14d cover for the same medicine).
          </EmptyState>
        )}

        <div className="panel-footer-meta">
          <span>Rebalancing candidates are evaluated in-memory across latest facility inventory snapshots.</span>
          <span>Requires physical inventory count and supply-chain officer sign-off.</span>
        </div>
      </div>
    </div>
  );
}
