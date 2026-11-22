"""Calendar dimension (gold_dim_date), built in pandas: a few thousand rows, holiday names come
from the `holidays` package, which has no Spark equivalent.

Business day = Monday to Friday and not one of the ten Ontario statutory holidays used by the
forecast features (calendar_features.HOLIDAY_IDS, Civic Holiday included). On-peak hours follow the
North American 5x16 convention: hour-ending 8 to 23 (07:00 to 23:00 EST) on business days.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from gridpulse.calendar_features import HOLIDAY_IDS, holidays_for_year

SEASONS = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
           6: "Summer", 7: "Summer", 8: "Summer", 9: "Fall", 10: "Fall", 11: "Fall"}  # fmt: skip
SEASON_ORDER = {"Winter": 1, "Spring": 2, "Summer": 3, "Fall": 4}
ONPEAK_HE = (8, 23)
_NAMES = {v: k for k, v in HOLIDAY_IDS.items()}


def season(month: int) -> str:
    return SEASONS[month]


def date_dimension(start: date, end: date) -> pd.DataFrame:
    """One row per date from start to end inclusive."""
    days = pd.date_range(start, end, freq="D")
    hol = {}
    for y in sorted({d.year for d in days}):
        hol.update(holidays_for_year(y))
    rows = []
    for ts in days:
        d = ts.date()
        hid = hol.get(d, 0)
        weekend = d.weekday() >= 5
        rows.append(
            {
                "date_key": d.year * 10000 + d.month * 100 + d.day,
                "est_date": d,
                "year": d.year,
                "quarter": (d.month - 1) // 3 + 1,
                "month": d.month,
                "month_name": ts.strftime("%B"),
                "month_short": ts.strftime("%b"),
                "month_start": d.replace(day=1),
                "year_month": f"{d.year}-{d.month:02d}",
                "day_of_month": d.day,
                "day_of_week": d.weekday(),  # 0 = Monday
                "day_name": ts.strftime("%A"),
                "day_short": ts.strftime("%a"),
                "is_weekend": weekend,
                "is_holiday": hid > 0,
                "holiday_name": _NAMES.get(hid) if 0 < hid < 99 else None,
                "is_business_day": not weekend and hid == 0,
                "season": SEASONS[d.month],
                "season_order": SEASON_ORDER[SEASONS[d.month]],
            }
        )
    return pd.DataFrame(rows)
