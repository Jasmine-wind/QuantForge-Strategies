"""One audited BTCUSDT settlement calendar, not a configurable or inferred tolerance.

Evidence: docs/DATA_AUDIT.md; 79 official archives, 7212 native records.
Matching verifies event identity only. Returned timestamps are never rounded.
"""
import pandas as pd


VERIFIED_START = pd.Timestamp("2020-01-01T00:00:00Z")
VERIFIED_END = pd.Timestamp("2026-08-01T00:00:00Z")
MAX_DELAY = pd.Timedelta(milliseconds=47)


def funding_policy():
    return {"version": "btc-usdt-native-8h-2020-2026-r1",
            "verified_start_inclusive": VERIFIED_START.isoformat(),
            "verified_end_exclusive": VERIFIED_END.isoformat(),
            "utc_hours": [0, 8, 16], "minimum_delay_ms": 0, "maximum_delay_ms": 47,
            "timestamp_precision": "integer milliseconds",
            "event_identity": "one actual record per nominal settlement; no deduplication or timestamp modification",
            "execution_interval": "actual timestamps in [start,end), not nominal timestamps",
            "boundary_coverage": "require records for settlement windows intersecting [start,end); retain boundary evidence outside execution interval",
            "evidence": "docs/DATA_AUDIT.md; 79 checksum-verified native Funding ZIPs / 7212 records"}


def validate_funding_schedule(funding, start, end, label):
    """Validate the whole supplied file before slicing by actual execution time.

    Boundary evidence: T is required when [T,T+47ms] intersects [start,end).
    A record outside the run may prove that settlement already happened / will
    happen later. Absence of that evidence is not assumed to mean zero Funding.
    """
    if not VERIFIED_START <= start < end <= VERIFIED_END:
        raise ValueError(f"{label}: unverified Funding schedule; expected run within "
                         f"[{VERIFIED_START.isoformat()}, {VERIFIED_END.isoformat()}), "
                         f"actual [{start.isoformat()}, {end.isoformat()})")
    # Nearest 8H point identifies the candidate event, then the fixed one-sided
    # delay is enforced. Rounding here does NOT alter the input index.
    nominal = funding.index.round("8h")
    matched = {}
    for actual, expected in zip(funding.index, nominal, strict=True):
        if not VERIFIED_START <= expected < VERIFIED_END:
            raise ValueError(f"{label}: unverified Funding settlement; expected audited coverage "
                             f"[{VERIFIED_START.isoformat()}, {VERIFIED_END.isoformat()}), "
                             f"nominal {expected.isoformat()}, actual {actual.isoformat()}")
        if actual.value % 1_000_000 or not pd.Timedelta(0) <= actual - expected <= MAX_DELAY:
            raise ValueError(f"{label}: off-schedule Funding; expected {expected.isoformat()} "
                             f"with integer-ms delay [0,47]ms, actual {actual.isoformat()}")
        if expected in matched:
            raise ValueError(f"{label}: duplicate Funding settlement; expected {expected.isoformat()}, "
                             f"actual [{matched[expected].isoformat()}, {actual.isoformat()}]")
        matched[expected] = actual
    first = max((start - MAX_DELAY).ceil("8h"), VERIFIED_START)
    for expected in pd.date_range(first, end, freq="8h", inclusive="left"):
        if expected not in matched:
            # Give the neighbouring actual records rather than just a missing bucket.
            nearby = [t.isoformat() for t in funding.index if abs(t - expected) <= pd.Timedelta(hours=8)]
            raise ValueError(f"{label}: missing Funding settlement; expected {expected.isoformat()} "
                             f"with delay [0,47]ms, actual records nearby {nearby}")
    return funding[(funding.index >= start) & (funding.index < end)]
