from decimal import Decimal

import db

BUDGET_TEXT = "The monthly answer budget is used up. Ask the admin to raise it."


def spent_this_month(group_external_id=None):
    where = "AND group_id = %s" if group_external_id else ""
    params = (group_external_id,) if group_external_id else ()
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT coalesce(sum(cost), 0) AS spent FROM query_log "
            f"WHERE ts >= date_trunc('month', now()) {where}",
            params,
        ).fetchone()
    return Decimal(row["spent"])


def exceeded(group, global_settings):
    cap = group["settings"]["monthly_cap_eur"]
    if cap is not None and spent_this_month(group["external_id"]) >= Decimal(str(cap)):
        return True
    gcap = global_settings["monthly_cap_eur"]
    return gcap is not None and spent_this_month() >= Decimal(str(gcap))
