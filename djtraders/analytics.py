"""
Calculations the dashboards share that are numbers, not charts: the summary tiles
(summary_stats) and the "Buy it again" list (reorder_due). Both take the same
DataFrame of order lines that every chart uses (lines_frame in charts.py), so a
customer, an employee and a supplier all get them by passing their own frame.
"""

import pandas as pd
from django.utils import timezone


def summary_stats(frame, today=None):
    """
    The numbers behind the summary tiles, from a frame of order lines. A dict, one
    key per number, so each tile is one block of the template:

    total_revenue, order_count (distinct orders), units, average_order, first_order
    and last_order (dates), days_since_last, anchor_year (the year of the last
    order), orders_in_year, units_in_year, revenue_change and average_order_change (percent, or
    None when last year has nothing to compare with).

    The change is year to date against year to date: January 1 to the last order
    of the anchor year, against January 1 to the same month and day a year earlier.
    Comparing a part-finished year with a whole one would make every user look like
    they were collapsing. has_orders is False for an empty frame (all numbers zero).
    """
    empty = {
        "has_orders": False, "total_revenue": 0, "order_count": 0, "units": 0, "average_order": 0,
        "first_order": None, "last_order": None, "days_since_last": None, "anchor_year": None,
        "orders_in_year": 0, "units_in_year": 0, "revenue_change": None, "average_order_change": None,
    }
    if frame.empty:
        return empty

    today = today or timezone.localdate()
    last = frame["order_date"].max()
    first = frame["order_date"].min()
    orders = frame["order_id"].nunique()
    revenue = float(frame["revenue"].sum())

    anchor_year = int(last.year)
    this_period = frame[frame["year"] == anchor_year]
    same_day_last_year = last - pd.DateOffset(years=1)  # Feb 29 becomes Feb 28
    last_period = frame[(frame["year"] == anchor_year - 1) & (frame["order_date"] <= same_day_last_year)]

    def percent_change(now, before):
        return None if not before else (now / before - 1) * 100

    this_revenue = float(this_period["revenue"].sum())
    last_revenue = float(last_period["revenue"].sum())
    this_orders = this_period["order_id"].nunique()
    last_orders = last_period["order_id"].nunique()
    this_average = this_revenue / this_orders if this_orders else 0
    last_average = last_revenue / last_orders if last_orders else 0

    return {
        "has_orders": True,
        "total_revenue": revenue,
        "order_count": orders,
        "units": int(frame["quantity"].sum()),
        "average_order": revenue / orders,
        "first_order": first.date(),
        "last_order": last.date(),
        "days_since_last": max((today - last.date()).days, 0),
        "anchor_year": anchor_year,
        "orders_in_year": this_orders,
        "units_in_year": int(this_period["quantity"].sum()),
        "revenue_change": percent_change(this_revenue, last_revenue),
        "average_order_change": percent_change(this_average, last_average),
    }


# region [WHY] how "due" is decided in reorder_due
# A product is "due" when a customer has bought it on at least MIN_ORDERS different
# orders (fewer is a coincidence, not a habit), the typical wait between those orders
# is at least MIN_GAP_DAYS (a gap of a few days is the same restocking split over two
# orders), and the days since the last one are past the typical gap but not past
# LAPSED_AFTER times it. The typical gap is the MEDIAN, so one long holiday wait does
# not stretch it. Past three typical gaps the customer has most likely stopped buying
# the product, and a reminder would be wrong.
# endregion
MIN_ORDERS = 3
MIN_GAP_DAYS = 14
LAPSED_AFTER = 3


def reorder_due(frame, today=None):
    """
    Products that are due for another order, one dict per customer-and-product pair:
    customer, product, orders (how many distinct orders held it), typical_gap and
    days_since (days), days_overdue, last_ordered (a date) and revenue_at_stake (the
    product's average revenue on one of those orders). Most overdue first. [] when no
    pair has a repeat pattern. A prompt to call, not a forecast: gaps are irregular.
    """
    if frame.empty:
        return []
    today = pd.Timestamp(today or timezone.localdate()).normalize()
    keys = ["customer_name", "product_name", "order_id"]
    per_order = (
        frame.groupby(keys, as_index=False)
        .agg(order_date=("order_date", "first"), revenue=("revenue", "sum"))
        .sort_values("order_date")
    )
    due = []
    for (customer, product), group in per_order.groupby(["customer_name", "product_name"]):
        if len(group) < MIN_ORDERS:
            continue
        typical_gap = group["order_date"].diff().dt.days.dropna().median()
        last_ordered = group["order_date"].iloc[-1]
        days_since = (today - last_ordered).days
        if typical_gap < MIN_GAP_DAYS or not (typical_gap < days_since <= LAPSED_AFTER * typical_gap):
            continue
        due.append({
            "customer": customer,
            "product": product,
            "orders": len(group),
            "typical_gap": round(typical_gap),
            "days_since": days_since,
            "days_overdue": round(days_since - typical_gap),
            "last_ordered": last_ordered.date(),
            "revenue_at_stake": float(group["revenue"].mean()),
        })
    return sorted(due, key=lambda row: row["days_overdue"], reverse=True)
