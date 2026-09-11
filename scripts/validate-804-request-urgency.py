#!/usr/bin/env python3
"""Regression checks for cached TURTO CRM request urgency dates."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sys


def main() -> None:
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))

    from price_lists_domain.platform import operational_refresh_804 as optimized
    from price_lists_domain.platform import worksets

    original = worksets._request_is_urgent
    optimized._iso_date.cache_clear()
    assert optimized._install_fast_request_urgency() is True
    current = worksets._request_is_urgent
    assert getattr(current, "_turto_804_cached_iso", False)

    today = date(2026, 9, 11)
    rows = [
        {"asked_date": "2026-09-07", "received_date": "", "archived": 0, "no_response": 0},
        {"asked_date": "2026-09-08", "received_date": "", "archived": 0, "no_response": 0},
        {"asked_date": "2026-09-01", "received_date": "2026-09-10", "archived": 0, "no_response": 0},
        {"asked_date": "2026-09-01", "received_date": "", "archived": 1, "no_response": 0},
        {"asked_date": "2026-09-01", "received_date": "", "archived": 0, "no_response": 1},
        {"asked_date": "", "received_date": "", "archived": 0, "no_response": 0},
        {"asked_date": "2026-99-99", "received_date": "", "archived": 0, "no_response": 0},
    ]
    for row in rows:
        assert current(row, today) == original(row, today), row

    # Repeated operational dates must hit the same shared ISO-date cache instead
    # of reparsing once per visible request row.
    repeated = {"asked_date": "2026-09-06", "received_date": "", "archived": 0, "no_response": 0}
    before = optimized._iso_date.cache_info()
    for _ in range(20):
        assert current(repeated, today) is True
    after = optimized._iso_date.cache_info()
    assert after.misses - before.misses <= 1
    assert after.hits - before.hits >= 19

    # Installation is idempotent and does not stack wrappers.
    installed = worksets._request_is_urgent
    assert optimized._install_fast_request_urgency() is True
    assert worksets._request_is_urgent is installed

    print("TURTO CRM 8.0.4 cached request urgency: OK")


if __name__ == "__main__":
    main()
