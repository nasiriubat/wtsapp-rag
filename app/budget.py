from decimal import Decimal

import db

BUDGET_TEXT = "The monthly answer budget is used up. Ask the admin to raise it."
# Caps, the cost page and the health card must agree on what a month is.
MONTH_SQL = "ts >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"


def spent_this_month(group_external_id=None):
    """(this group's spend, everyone's spend) for the current UTC calendar month."""
    with db.connect() as conn:
        row = conn.execute(
            f"""
            SELECT coalesce(sum(cost) FILTER (WHERE group_id = %s), 0) AS grp, coalesce(sum(cost), 0) AS total
            FROM query_log WHERE {MONTH_SQL}
            """,
            (group_external_id,),
        ).fetchone()
    return Decimal(row["grp"]), Decimal(row["total"])


def exceeded(group, global_settings):
    cap, gcap = group["settings"]["monthly_cap_eur"], global_settings["monthly_cap_eur"]
    if cap is None and gcap is None:
        return False
    grp, total = spent_this_month(group["external_id"])
    return (cap is not None and grp >= Decimal(str(cap))) or (
        gcap is not None and total >= Decimal(str(gcap))
    )
