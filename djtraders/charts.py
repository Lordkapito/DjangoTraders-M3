"""
Chart helpers: they turn order lines into pandas DataFrames and DataFrames into
Plotly chart HTML, so the customer, employee and supplier pages all draw their
charts the same way. A model method (for example Customer.annual_orders_plot)
pulls its order lines out of the database with lines_frame, groups them with
pandas, and hands the result to bar_figure or line_figure.

Revenue is each line's unit_price * quantity * (1 - discount), the same formula
as OrderDetail.line_total -- not Product.unit_price, which is today's list price
and ignores discounts and any price change since the order was placed.
"""

import calendar

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.colors import qualitative

# region [WHY] one fixed color per bar
# A bar chart gives each x value its own color, picked by position in a stable
# ordering (bar_figure), so the same category or product keeps its color in every
# chart. With more bars than colors, the colors repeat. Any of Plotly's built-in
# qualitative palettes works here; see https://plotly.com/python/colors/
# endregion
CHART_COLORS = qualitative.Set3


def lines_frame(lines):
    """
    Turns a queryset of OrderDetail rows into a DataFrame, one row per line, with
    the columns the charts group on: order_id, order_date, year, month,
    product_name, category_name, discontinued (1/0), customer_name, quantity and revenue (empty when
    there are no lines). .values() asks the database for just those columns as
    plain dicts instead of building a model object per row.
    """
    rows = lines.values(
        "order_id",
        "order__order_date",
        "order__customer__company_name",
        "product__product_name",
        "product__category__category_name",
        "product__discontinued",
        "unit_price",
        "quantity",
        "discount",
    )
    frame = pd.DataFrame(list(rows))
    if frame.empty:
        return frame
    frame = frame.rename(columns={
        "order__order_date": "order_date",
        "order__customer__company_name": "customer_name",
        "product__product_name": "product_name",
        "product__category__category_name": "category_name",
        "product__discontinued": "discontinued",
    })
    frame["order_date"] = pd.to_datetime(frame["order_date"])
    frame["year"] = frame["order_date"].dt.year
    frame["month"] = frame["order_date"].dt.month
    frame["revenue"] = frame["unit_price"] * frame["quantity"] * (1 - frame["discount"])
    frame["category_name"] = frame["category_name"].fillna("Uncategorized")
    frame["customer_name"] = frame["customer_name"].fillna("Unknown customer")
    return frame


def figure_html(figure):
    """
    Turns a Plotly figure into an HTML <div> plus the small <script> that draws
    it. include_plotlyjs=False leaves the ~4 MB plotly.js library out of every
    chart; the page loads it once itself.
    """
    # The chart title is styled like a card title in the page (Bootstrap's h5: 20px, dark
    # text, flush left in the card), so a chart and an HTML card heading look alike.
    figure.update_layout(
        template="plotly_white", margin={"l": 40, "r": 20, "t": 50, "b": 40},
        title={"x": 0, "xref": "container", "xanchor": "left", "font": {"size": 20, "color": "#212529", "family": '"Segoe UI", Tahoma, "Trebuchet MS", sans-serif'}},
    )
    return figure.to_html(full_html=False, include_plotlyjs=False)


def _color_map(names):
    """Maps each distinct name to a CHART_COLORS entry by its position in sorted order (repeating once the palette runs out)."""
    ordered = sorted(set(names), key=str)
    return {name: CHART_COLORS[i % len(CHART_COLORS)] for i, name in enumerate(ordered)}


def bar_figure(data, category, value, title, labels, color_names=None,
               horizontal=False, height=None, trend=True, text=None, hover=None):
    """
    Builds one bar chart with Plotly Express: a bar per row of data, each bar its
    own color (CHART_COLORS) and labeled with its value, plus (trend=True) a
    dashed least-squares trend line over the bars.

    data is a DataFrame already in display order; category is the column of bar
    names and value the column of bar lengths. labels names the axes, and
    color_names is the full set of names to take colors from, so a chart showing
    only the top ten products keeps the colors it has in a chart showing all of
    them.

    The trend line (np.polyfit, degree 1, clamped at zero) says something about
    time-ordered bars such as months or years; bars sorted by size pass
    trend=False. text replaces the bar labels, and hover replaces the hover box's
    text (one string per bar, with <br> for line breaks). height is always
    explicit: left unset, Plotly sizes to its container, and inside an
    equal-height card the chart would collapse.
    """
    colors = _color_map(data[category] if color_names is None else color_names)
    names = list(data[category])
    values = list(data[value])
    if text is None:
        text = [f"{v:,.0f}" if value == "quantity" else f"${v:,.0f}" for v in values]

    # px.bar draws the bars and names the axes from labels.
    x, y = (value, category) if horizontal else (category, value)
    figure = px.bar(data, x=x, y=y, orientation="h" if horizontal else "v",
                    title=title, labels=labels, height=height or 420)

    # One color per bar, a label at the end of each bar, and a hover box that shows
    # the bar's name and label (without a hovertemplate Plotly prints raw axis numbers).
    tip = "<b>%{y}</b><br>%{text}<extra></extra>" if horizontal else "<b>%{x}</b><br>%{text}<extra></extra>"
    figure.update_traces(
        marker_color=[colors[name] for name in names], text=text, textposition="outside",
        cliponaxis=False, textfont_size=11, customdata=hover,
        hovertemplate="%{customdata}<extra></extra>" if hover is not None else tip,
    )

    if trend and len(values) >= 2:
        slope, intercept = np.polyfit(np.arange(len(values)), values, 1)
        fitted = list(np.maximum(slope * np.arange(len(values)) + intercept, 0))
        prefix = "" if value == "quantity" else "$"
        line = {"mode": "lines", "name": "Trend", "line": {"color": "#444444", "width": 2, "dash": "dash"},
                "hovertemplate": "Trend: " + prefix + "%{y:,.0f}<extra></extra>"}
        figure.add_scatter(**({"x": fitted, "y": names} if horizontal else {"x": names, "y": fitted}), **line)

    # Stretch the value axis past the longest bar so the labels fit; long labels
    # ("$56,526 (10.7%)") need more room than short ones.
    room = 1.25 if max(len(label) for label in text) <= 8 else 1.55
    if not horizontal and room > 1.25:
        # Plotly shrinks a label that is wider than its bar (constraintext), which makes
        # long labels on narrow columns unreadable; tilt them and let them overhang.
        figure.update_traces(textangle=-45, constraintext="none", textfont_size=13, selector={"type": "bar"})
        room = 1.9
        figure.update_xaxes(range=[-0.9, len(names) - 0.4])  # room at the left so the first label clears the axis
    (figure.update_xaxes if horizontal else figure.update_yaxes)(range=[0, max(values) * room])
    figure.update_layout(bargap=0.2, legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "right", "x": 1.0})
    if not horizontal:
        figure.update_xaxes(type="category")
    return figure_html(figure)


def line_figure(data, x, y, title, labels, height=360, hover=None):
    """
    Builds one line chart with Plotly Express, with a marker on each point, for
    values in time order such as revenue by month (bars suit separate groups, a
    line suits a sequence). data is a DataFrame already in time order; x is the
    column of point names and y the column of values.

    The line is smoothed (line_shape="spline"), so between two markers it can dip
    a little; the markers stay on the real values. Like bar_figure it takes hover
    text and ends in figure_html. The value axis starts at zero so a quiet month
    looks quiet, and the x names are categories so Plotly keeps them in the order
    given.
    """
    figure = px.line(data, x=x, y=y, markers=True, line_shape="spline", title=title, labels=labels, height=height)
    figure.update_traces(line={"color": CHART_COLORS[0], "width": 3, "smoothing": 0.8}, marker={"size": 7},
                         customdata=hover, hovertemplate="%{customdata}<extra></extra>", showlegend=False)
    figure.update_xaxes(type="category")
    figure.update_yaxes(rangemode="tozero", tickprefix="$")
    return figure_html(figure)


def top_with_other(data, category, value, count):
    """
    The `count` largest rows of data by value, largest first, plus one "Other" row
    adding up the rest when there are any. A pie is only readable with a few
    slices, so pie_figure is fed this.
    """
    ordered = data.sort_values(value, ascending=False)
    top = ordered.head(count)
    if len(ordered) > count:
        other = pd.DataFrame({category: ["Other"], value: [ordered[value].iloc[count:].sum()]})
        top = pd.concat([top, other], ignore_index=True)
    return top


def pie_figure(data, category, value, title, color_names=None, height=420):
    """
    Builds one pie chart with Plotly Express: a slice per row of data, colored like
    the bar charts (a name keeps its color; "Other" is gray) and labeled with its
    percent. The hover box shows the name, its dollars and its percent, so value
    should be a dollar amount. Use top_with_other first so there are few slices.
    """
    colors = _color_map(data[category] if color_names is None else color_names)
    colors["Other"] = "lightgray"
    figure = px.pie(data, names=category, values=value, title=title, height=height,
                    color=category, color_discrete_map=colors)
    figure.update_traces(sort=False, textinfo="percent",
                         hovertemplate="<b>%{label}</b><br>$%{value:,.0f} (%{percent})<extra></extra>")
    return figure_html(figure)


# region [WHY] chart builders shared by the customer and supplier dashboards
# Both portals draw the same category, unit-share and top-product charts from a frame
# of order lines; only the scope of the lines differs (order__customer=self or
# product__supplier=self). So the grouping and drawing live here once, and each
# model method only builds its own frame, filters it and calls one of these.
# Every builder returns chart HTML, or None when there is nothing to draw.
# endregion

def filter_year(frame, year):
    """The frame limited to one year (year=None keeps every year). An empty frame stays empty."""
    if year is None or frame.empty:
        return frame
    return frame[frame["year"] == year]


def _bar_height(count):
    """A horizontal chart's pixel height: room for every bar (the same rule the employee charts use)."""
    per_bar = 32 if count <= 12 else 24
    return max(420, per_bar * count + 100)


def annual_revenue_figure(frame):
    """Revenue by year as bars with a trend line (the supplier's copy of Customer.annual_orders_plot)."""
    if frame.empty:
        return None
    annual = frame.groupby("year", as_index=False)["revenue"].sum()
    annual["year"] = annual["year"].astype(str)
    return bar_figure(annual, "year", "revenue", "Revenue by year",
                      {"year": "Year", "revenue": "Revenue ($)"})


def monthly_revenue_figure(frame, year):
    """
    Revenue for each of the twelve months of one year (None when that year has no
    lines). reindex(range(1, 13), fill_value=0) keeps a quiet month on the chart as $0.
    """
    frame = filter_year(frame, year)
    if frame.empty:
        return None
    monthly = (
        frame.groupby("month")["revenue"].sum()
        .reindex(range(1, 13), fill_value=0)
        .reset_index()
    )
    monthly["month"] = [calendar.month_abbr[m] for m in monthly["month"]]
    return bar_figure(monthly, "month", "revenue", f"Revenue by month, {year}",
                      {"month": "Month", "revenue": "Revenue ($)"})


def category_revenue_figure(frame, top=None):
    """
    Revenue by category as columns, biggest first; top keeps the largest N
    (None = all). Sorted by size, so there is no trend line.
    """
    if frame.empty:
        return None
    by_category = (
        frame.groupby("category_name", as_index=False)["revenue"].sum()
        .sort_values("revenue", ascending=False)
    )
    shown = by_category.head(top) if top else by_category
    title = f"Top {len(shown)} categories by revenue" if top and top < len(by_category) else "Revenue by category"
    return bar_figure(shown, "category_name", "revenue", title,
                      {"category_name": "Category", "revenue": "Revenue ($)"},
                      color_names=by_category["category_name"], trend=False)


def unit_share_figure(frame, top=None, kind="pie"):
    """
    Each category's share of the units sold, as a pie (kind="pie": the largest
    N slices plus "Other") or as horizontal bars of percent (kind="bar"). The
    percent is always of ALL units, so the bars of a Top 5 chart do not add to 100.
    """
    if frame.empty:
        return None
    by_category = (
        frame.groupby("category_name", as_index=False)["quantity"].sum()
        .sort_values("quantity", ascending=False)
    )
    colors = _color_map(by_category["category_name"])
    if kind == "pie":
        slices = top_with_other(by_category, "category_name", "quantity", min(top or 10, 10))
        colors["Other"] = "lightgray"
        figure = px.pie(slices, names="category_name", values="quantity", title="Unit share by category",
                        height=420, color="category_name", color_discrete_map=colors)
        figure.update_traces(sort=False, textinfo="percent",
                             hovertemplate="<b>%{label}</b><br>%{value:,} units (%{percent})<extra></extra>")
        return figure_html(figure)
    by_category["percent"] = by_category["quantity"] / by_category["quantity"].sum() * 100
    shown = by_category.head(top) if top else by_category
    shown = shown.iloc[::-1]  # Plotly draws the first horizontal bar at the bottom
    text = [f"{row.percent:.1f}% ({row.quantity:,.0f} units)" for row in shown.itertuples()]
    return bar_figure(shown, "category_name", "percent", "Unit share by category (% of units)",
                      {"category_name": "Category", "percent": "Share of units (%)"},
                      color_names=by_category["category_name"], horizontal=True,
                      height=_bar_height(len(shown)), trend=False, text=text)


def top_products_figure(frame, measure="revenue", top=10):
    """
    The largest N products (None = all) by measure: "revenue" in dollars or "units"
    sold. Horizontal bars, largest at the top, each labeled with its amount and its
    percent of the whole.
    """
    if frame.empty:
        return None
    column = "revenue" if measure == "revenue" else "quantity"
    by_product = (
        frame.groupby("product_name", as_index=False)[column].sum()
        .sort_values(column, ascending=False)
    )
    total = by_product[column].sum()
    shown = (by_product.head(top) if top else by_product).iloc[::-1]
    if measure == "revenue":
        text = [f"${row[1]:,.0f} ({row[1] / total * 100:.1f}%)" for row in shown[["product_name", column]].itertuples(index=False)]
        label = "revenue"
    else:
        text = [f"{row[1]:,.0f} ({row[1] / total * 100:.1f}%)" for row in shown[["product_name", column]].itertuples(index=False)]
        label = "units"
    title = f"Top {len(shown)} products by {label}" if top and top < len(by_product) else f"Products by {label}"
    return bar_figure(shown, "product_name", column, title,
                      {"product_name": "Product", column: "Revenue ($)" if measure == "revenue" else "Units sold"},
                      color_names=by_product["product_name"], horizontal=True,
                      height=_bar_height(len(shown)), trend=False, text=text)


def share_change_figure(frame, start, end):
    """
    Which products gained or lost share of revenue between two years: for each
    product, its percent of the year's revenue in `end` minus its percent in
    `start`, in percentage points, as diverging horizontal bars (gains right,
    losses left). None when neither year has lines. At most the 15 biggest movers.
    """
    both = frame[frame["year"].isin([start, end])] if not frame.empty else frame
    if both.empty:
        return None
    revenue = both.pivot_table(index="product_name", columns="year", values="revenue",
                               aggfunc="sum", fill_value=0.0)
    for year in (start, end):
        if year not in revenue.columns:
            revenue[year] = 0.0
    share = revenue.div(revenue.sum(axis=0).replace(0, np.nan), axis=1).fillna(0) * 100
    table = pd.DataFrame({"start": share[start], "end": share[end]})
    table["change"] = table["end"] - table["start"]
    table = table[(table["start"] > 0) | (table["end"] > 0)]
    table = table.reindex(table["change"].abs().sort_values(ascending=False).index).head(15)
    table = table.sort_values("change")  # biggest loss at the bottom ... biggest gain at the top
    names = list(table.index)
    changes = list(table["change"])
    hover = [f"<b>{name}</b><br>{start}: {row.start:.1f}% of revenue<br>{end}: {row.end:.1f}%<br>Change: {row.change:+.1f} points"
             for name, row in zip(names, table.itertuples())]
    figure = go.Figure(go.Bar(
        x=changes, y=names, orientation="h",
        text=[f"{c:+.1f}" for c in changes], textposition="outside", cliponaxis=False,
        marker_color=[CHART_COLORS[0] if c >= 0 else CHART_COLORS[3] for c in changes],
        customdata=hover, hovertemplate="%{customdata}<extra></extra>",
    ))
    spread = max(abs(c) for c in changes) if changes else 1
    figure.update_layout(
        title=f"Change in share of revenue, {start} to {end}", height=_bar_height(len(names)),
        xaxis_title="Change in share of revenue (percentage points)", bargap=0.2,
    )
    figure.update_xaxes(range=[-spread * 1.3, spread * 1.3], zeroline=True, zerolinewidth=2, zerolinecolor="#444444")
    figure.update_yaxes(type="category")
    return figure_html(figure)


def month_pattern_figure(frame, measure="revenue", view="amount"):
    """
    A year-by-month heatmap of one measure ("revenue", "units" or "orders"). view
    "amount" shades the real numbers; view "share" shows each month as a percent of
    its own year, which makes a year bunched into a few months stand out. The title
    says how much of all-time activity the three busiest calendar months hold.
    """
    if frame.empty:
        return None
    if measure == "revenue":
        grouped, label = frame.groupby(["year", "month"])["revenue"].sum(), "revenue"
    elif measure == "units":
        grouped, label = frame.groupby(["year", "month"])["quantity"].sum(), "units"
    else:
        grouped, label = frame.groupby(["year", "month"])["order_id"].nunique(), "orders"
    grid = grouped.unstack(fill_value=0).reindex(columns=range(1, 13), fill_value=0).sort_index()
    by_month = grid.sum(axis=0)
    top3 = by_month.sort_values(ascending=False).head(3).sum() / by_month.sum() * 100 if by_month.sum() else 0
    values = grid
    if view == "share":
        values = grid.div(grid.sum(axis=1).replace(0, np.nan), axis=0).fillna(0) * 100
    money = measure == "revenue" and view == "amount"
    figure = go.Figure(go.Heatmap(
        z=values.values, x=[calendar.month_abbr[m] for m in range(1, 13)], y=[str(y) for y in values.index],
        colorscale="Blues", xgap=2, ygap=2,
        texttemplate="%{z:.0f}%" if view == "share" else ("$%{z:,.0f}" if money else "%{z:,.0f}"),
        hovertemplate="<b>%{y} %{x}</b><br>%{z:,.1f}" + ("%" if view == "share" else "") + "<extra></extra>",
        colorbar={"title": "% of year" if view == "share" else label.capitalize()},
    ))
    figure.update_layout(
        title=f"Monthly {label} pattern (the 3 busiest months hold {top3:.0f}% of all {label})",
        height=max(280, 62 * len(values) + 140),
    )
    figure.update_yaxes(type="category", autorange="reversed")
    figure.update_xaxes(type="category")
    return figure_html(figure)
