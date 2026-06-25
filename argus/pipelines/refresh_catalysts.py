from __future__ import annotations

from datetime import date, datetime, time
import logging
from argus.core.db import session_scope, safe_execute_query
from argus.core.models import CatalystEvent, CatalystImpactSnapshot, Company


logger = logging.getLogger(__name__)


def _parse_date(val) -> date | None:
    if val is None:
        return None
    if isinstance(val, str):
        if " " in val:
            val = val.split(" ")[0]
        return date.fromisoformat(val)
    if isinstance(val, datetime):
        return val.date()
    return val


def _parse_datetime(val) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        return datetime.fromisoformat(val)
    return None


def _source_key(*parts) -> str:
    return ":".join(str(part) for part in parts if part is not None and str(part) != "")


def _event_timing(details: dict) -> str:
    timing = details.get("timing") or details.get("session") or details.get("market_session")
    if timing:
        return str(timing).strip().lower()

    accepted_at = _parse_datetime(details.get("acceptance_datetime"))
    if accepted_at:
        if accepted_at.time() < time(9, 30):
            return "bmo"
        if accepted_at.time() >= time(16, 0):
            return "amc"
    return "unknown"


def _anchor_index_for_event(
    price_list: list[tuple[date, float | None]],
    date_to_idx: dict[date, int],
    event_date: date,
    details: dict,
) -> int | None:
    timing = _event_timing(details)
    if timing in {"bmo", "before_market", "before_open", "pre_market"}:
        prior_dates = [d for d, _ in price_list if d < event_date]
        return date_to_idx[prior_dates[-1]] if prior_dates else None

    if event_date in date_to_idx:
        return date_to_idx[event_date]

    prior_dates = [d for d, _ in price_list if d < event_date]
    if prior_dates:
        return date_to_idx[prior_dates[-1]]
    future_dates = [d for d, _ in price_list if d >= event_date]
    return date_to_idx[future_dates[0]] if future_dates else None


def _target_company_ids_for_cross_event(companies: list[Company], trigger: Company) -> list[int]:
    targets: list[int] = []
    for company in companies:
        if company.id == trigger.id or company.is_benchmark:
            continue
        if trigger.symbol.upper() == "NVDA":
            targets.append(company.id)
        elif trigger.is_hyperscaler and (not trigger.sector or company.sector == trigger.sector):
            targets.append(company.id)
    return targets


def refresh_catalyst_impact() -> dict[str, int]:
    """Ingest earnings events, SEC filings, and cross-stock catalysts, then compute impact snapshots.

    Idempotent and updates/backfills snapshots as new price history becomes available.
    """
    with session_scope() as session:
        # 1. Load active companies
        companies = session.query(Company).filter(Company.is_active.is_(True)).all()
        company_map = {c.id: c for c in companies}
        company_ids = list(company_map.keys())

        if not company_ids:
            logger.warning("No active companies found for catalyst ingestion.")
            return {"events_created": 0, "snapshots_updated": 0}

        events_created = 0

        # Load existing catalyst events into memory to avoid duplicates
        existing_events = {}
        for row in session.query(CatalystEvent).all():
            key = row.source_key or _source_key(row.event_type, _parse_date(row.date))
            existing_events.setdefault(row.company_id, {}).setdefault(row.event_type, set()).add(key)

        def _add_event(cid, etype, edate, details=None, source_key=None):
            nonlocal events_created
            parsed_edate = _parse_date(edate)
            if not parsed_edate:
                return
            event_key = source_key or _source_key(etype, parsed_edate)
            if cid in existing_events and etype in existing_events[cid] and event_key in existing_events[cid][etype]:
                return
            
            evt = CatalystEvent(
                company_id=cid,
                event_type=etype,
                date=parsed_edate,
                details=details,
                source_key=event_key,
            )
            session.add(evt)
            events_created += 1
            existing_events.setdefault(cid, {}).setdefault(etype, set()).add(event_key)

        # A. Ingest Earnings Events
        logger.info("Ingesting earnings events...")
        earnings_rows = safe_execute_query(
            session,
            f"""
            SELECT id, company_id, event_date, fiscal_period, eps_actual, eps_estimate,
                   revenue_actual, revenue_estimate
            FROM earnings_events
            WHERE company_id IN ({','.join(map(str, company_ids))})
            """,
            type_map={"event_date": "date"},
        )

        for row in earnings_rows:
            cid = row["company_id"]
            edate = row["event_date"]
            if not edate:
                continue
            
            # Details payload
            details = {
                "fiscal_period": row["fiscal_period"],
                "eps_actual": row["eps_actual"],
                "eps_estimate": row["eps_estimate"],
                "revenue_actual": row["revenue_actual"],
                "revenue_estimate": row["revenue_estimate"]
            }
            # Add direct earnings event
            _add_event(cid, "earnings", edate, details, _source_key("earnings", row["id"]))

            # Add cross-stock events
            comp = company_map[cid]
            if comp.symbol.upper() == "NVDA":
                for other_cid in _target_company_ids_for_cross_event(companies, comp):
                    _add_event(
                        other_cid,
                        "nvda_earnings",
                        edate,
                        {"trigger_symbol": "NVDA", "trigger_company_id": cid},
                        _source_key("nvda_earnings", cid, row["id"]),
                    )
            elif comp.is_hyperscaler:
                for other_cid in _target_company_ids_for_cross_event(companies, comp):
                    _add_event(
                        other_cid,
                        "hyperscaler_earnings",
                        edate,
                        {"trigger_symbol": comp.symbol, "trigger_company_id": cid},
                        _source_key("hyperscaler_earnings", cid, row["id"]),
                    )

        # B. Ingest SEC Filings (10-K, 10-Q, 8-K)
        logger.info("Ingesting SEC filings...")
        filing_rows = safe_execute_query(
            session,
            f"""
            SELECT id, company_id, form, filing_date, acceptance_datetime, accession_no, filing_detail_url
            FROM sec_filings
            WHERE form IN ('10-K', '10-Q', '8-K') AND company_id IN ({','.join(map(str, company_ids))})
            """,
            type_map={"filing_date": "date", "acceptance_datetime": "datetime"},
        )

        form_mapping = {
            "10-K": "sec_10k",
            "10-Q": "sec_10q",
            "8-K": "sec_8k"
        }

        for row in filing_rows:
            cid = row["company_id"]
            form = row["form"]
            edate = row["filing_date"]
            if not edate:
                continue

            etype = form_mapping.get(form)
            if not etype:
                continue

            details = {
                "accession_no": row["accession_no"],
                "filing_detail_url": row["filing_detail_url"]
            }
            accepted_at = _parse_datetime(row.get("acceptance_datetime"))
            if accepted_at:
                details["acceptance_datetime"] = accepted_at.isoformat()
                if accepted_at.time() >= time(16, 0):
                    details["after_close"] = True
            _add_event(cid, etype, edate, details, _source_key(etype, row["accession_no"]))

        session.commit()
        logger.info("Created %s new catalyst events.", events_created)

        # C. Compute and Update CatalystImpactSnapshots
        logger.info("Loading price history for impact snapshot calculations...")
        price_rows = safe_execute_query(
            session,
            """
            SELECT company_id, date, adj_close
            FROM price_bars
            WHERE interval = '1d'
            ORDER BY date ASC
            """,
            type_map={"date": "date"},
        )

        prices_by_company = {}
        for p in price_rows:
            prices_by_company.setdefault(p["company_id"], []).append((p["date"], p["adj_close"]))

        # Load all existing snapshots into a dictionary
        snapshots = {s.catalyst_event_id: s for s in session.query(CatalystImpactSnapshot).all()}

        # Load all catalyst events
        all_events = session.query(CatalystEvent).all()
        snapshots_updated = 0

        logger.info("Calculating catalyst impact snapshots...")
        for evt in all_events:
            price_list = prices_by_company.get(evt.company_id, [])
            if not price_list:
                continue

            # Map date to index
            date_to_idx = {p[0]: idx for idx, p in enumerate(price_list)}
            parsed_evt_date = _parse_date(evt.date)
            details = evt.details or {}
            curr_idx = _anchor_index_for_event(price_list, date_to_idx, parsed_evt_date, details)
            if curr_idx is None:
                continue

            # M1 return (1 trading day before to event date)
            ret_m1 = None
            if curr_idx - 1 >= 0:
                denom = price_list[curr_idx - 1][1]
                ret_m1 = (price_list[curr_idx][1] - denom) / denom if denom and denom > 0 else 0.0

            # P1 return (event date to 1 trading day after)
            ret_p1 = None
            if curr_idx + 1 < len(price_list):
                denom = price_list[curr_idx][1]
                ret_p1 = (price_list[curr_idx + 1][1] - denom) / denom if denom and denom > 0 else 0.0

            # P1 to P5 return
            ret_p5 = None
            if curr_idx + 6 < len(price_list):
                denom = price_list[curr_idx + 1][1]
                ret_p5 = (price_list[curr_idx + 6][1] - denom) / denom if denom and denom > 0 else 0.0

            # P1 to P20 return & drawdown
            ret_p20 = None
            max_dd_20 = None
            if curr_idx + 21 < len(price_list):
                denom = price_list[curr_idx + 1][1]
                ret_p20 = (price_list[curr_idx + 21][1] - denom) / denom if denom and denom > 0 else 0.0
                
                # Max drawdown over 20 trading sessions after P1.
                peak = price_list[curr_idx + 1][1]
                max_dd = 0.0
                for i in range(1, 22):
                    p_val = price_list[curr_idx + i][1]
                    peak = max(peak, p_val)
                    dd = (p_val - peak) / peak if peak and peak > 0 else 0.0
                    max_dd = min(max_dd, dd)
                max_dd_20 = max_dd

            # Check if snapshot already exists
            snap = snapshots.get(evt.id)
            if snap is None:
                # Create a new snapshot
                snap = CatalystImpactSnapshot(
                    catalyst_event_id=evt.id,
                    return_m1_to_event=ret_m1,
                    return_event_to_p1=ret_p1,
                    return_p1_to_p5=ret_p5,
                    return_p1_to_p20=ret_p20,
                    max_drawdown_p20=max_dd_20
                )
                session.add(snap)
                snapshots_updated += 1
            else:
                # Recompute snapshots when methodology changes or new information arrives.
                changed = False
                if ret_m1 is not None and snap.return_m1_to_event != ret_m1:
                    snap.return_m1_to_event = ret_m1
                    changed = True
                if ret_p1 is not None and snap.return_event_to_p1 != ret_p1:
                    snap.return_event_to_p1 = ret_p1
                    changed = True
                if ret_p5 is not None and snap.return_p1_to_p5 != ret_p5:
                    snap.return_p1_to_p5 = ret_p5
                    changed = True
                if ret_p20 is not None and snap.return_p1_to_p20 != ret_p20:
                    snap.return_p1_to_p20 = ret_p20
                    changed = True
                if max_dd_20 is not None and snap.max_drawdown_p20 != max_dd_20:
                    snap.max_drawdown_p20 = max_dd_20
                    changed = True
                if changed:
                    snapshots_updated += 1

        session.commit()
        logger.info("Saved/updated %s impact snapshots.", snapshots_updated)

    return {"events_created": events_created, "snapshots_updated": snapshots_updated}
