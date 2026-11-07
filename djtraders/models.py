"""
The app's models, cleaned up from `manage.py inspectdb` (rev_engineer_models.py
has the raw output). Every model is managed=False, because this app reads a
database Django didn't create and must never migrate those tables. Names are
singular, models are ordered so each is defined before anything that references
it by bare class name, and every foreign key has a real on_delete (inspectdb
defaults to DO_NOTHING).

On top of that the models add computed @property values (e.g.
Order.order_total), search() classmethods that back the list pages,
authenticate() classmethods for the hand-rolled logins (no django.contrib.auth),
and, for the dashboards, methods that return Plotly charts built with the
helpers in charts.py.
"""

import calendar

import pandas as pd
import plotly.graph_objects as go
from django.db import models
from django.db.models import Count, ExpressionWrapper, F, FloatField, Sum

from .analytics import reorder_due, summary_stats
from .charts import (
    CHART_COLORS,
    annual_revenue_figure,
    bar_figure,
    category_revenue_figure,
    figure_html,
    filter_year,
    line_figure,
    lines_frame,
    month_pattern_figure,
    monthly_revenue_figure,
    pie_figure,
    share_change_figure,
    top_products_figure,
    top_with_other,
    unit_share_figure,
)


class Category(models.Model):
    """A product category. Defined before Product so Product.category can use the bare class name."""
    category_id = models.SmallIntegerField(primary_key=True)
    category_name = models.CharField(max_length=15)
    description = models.TextField(blank=True, null=True)
    picture = models.BinaryField(blank=True, null=True)

    class Meta:
        """Meta configures the table, not a column. managed=False: the table exists, so Django must not migrate it. db_table: its real name."""
        managed = False
        db_table = 'categories'


class Customer(models.Model):
    """A DjangoTraders customer. No foreign keys, so no on_delete concerns."""
    customer_id = models.CharField(primary_key=True, max_length=5)
    company_name = models.CharField(max_length=40)
    contact_name = models.CharField(max_length=30, blank=True, null=True)
    contact_title = models.CharField(max_length=30, blank=True, null=True)
    address = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=15, blank=True, null=True)
    region = models.CharField(max_length=15, blank=True, null=True)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=15, blank=True, null=True)
    phone = models.CharField(max_length=24, blank=True, null=True)
    fax = models.CharField(max_length=24, blank=True, null=True)
    password = models.CharField(db_column='Password', max_length=64, blank=True, null=True)  # Field name made lowercase.
    inactive_date = models.DateField(blank=True, null=True)

    @property
    def formatted_address(self):
        """This customer's address fields joined into one line, blanks skipped."""
        parts = [self.address, self.city, self.region, self.postal_code, self.country]
        return ", ".join(part for part in parts if part)

    # region [WHY] charts built from a DataFrame
    # Each *_plot method pulls this customer's placed order lines into a DataFrame
    # (_order_lines_frame), groups and sums them with pandas, and hands the result to
    # bar_figure, which returns chart HTML a template prints with |safe.
    # endregion
    def _order_lines_frame(self):
        """
        Every line on this customer's placed orders as a DataFrame (see
        lines_frame in charts.py). An order with no order_date is an unplaced
        cart and is left out.
        """
        return lines_frame(OrderDetail.objects.filter(
            order__customer=self, order__order_date__isnull=False
        ))

    def order_years(self):
        """Distinct years this customer has placed orders in, newest first."""
        years = self.order_set.filter(order_date__isnull=False).dates("order_date", "year")
        return sorted((d.year for d in years), reverse=True)

    def annual_orders_plot(self):
        """Bar chart of this customer's total revenue for each year."""
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        annual = frame.groupby("year", as_index=False)["revenue"].sum()
        annual["year"] = annual["year"].astype(str)
        return bar_figure(
            annual, "year", "revenue", "Revenue by year",
            {"year": "Year", "revenue": "Revenue ($)"},
        )

    def orders_placed_plot(self, year):
        """
        Bar chart of this customer's revenue for each month of one year (what the
        dashboard's year dropdown loads), or None when that year has no placed
        orders. reindex(range(1, 13), fill_value=0) puts all twelve months on the
        chart: without it a month with no orders would be missing instead of $0.
        """
        frame = self._order_lines_frame()
        frame = frame[frame["year"] == year]
        if frame.empty:
            return None
        monthly = (
            frame.groupby("month")["revenue"].sum()
            .reindex(range(1, 13), fill_value=0)
            .reset_index()
        )
        monthly["month"] = [calendar.month_abbr[m] for m in monthly["month"]]
        return bar_figure(
            monthly, "month", "revenue", f"Revenue by month, {year}",
            {"month": "Month", "revenue": "Revenue ($)"},
        )

    def dashboard_stats(self):
        """
        The four summary tiles' numbers (Total Revenue with its year-to-date change,
        Orders, Average Order, Last Order with the days since it) as one dict, one key
        per number. See analytics.summary_stats. has_orders is False with no orders.
        """
        return summary_stats(self._order_lines_frame())

    def category_revenue_plot(self, top=None, year=None):
        """
        Revenue by category as columns, biggest first (None when there is nothing to
        draw). top keeps the largest N categories (None = all); year limits it to one
        year (None = all years). The bars are sorted by size, not by time, so there is
        no trend line.
        """
        return category_revenue_figure(filter_year(self._order_lines_frame(), year), top)

    def unit_share_plot(self, top=None, year=None, kind="pie"):
        """Each category's share of the units this customer bought, as a "pie" or as percent "bar"s (see charts.unit_share_figure)."""
        return unit_share_figure(filter_year(self._order_lines_frame(), year), top, kind)

    def top_products_plot(self, measure="revenue", top=10, hide_discontinued=False):
        """
        The customer's top N products by "revenue" or "units" (None = all products).
        hide_discontinued leaves out products no longer sold.
        """
        frame = self._order_lines_frame()
        if hide_discontinued and not frame.empty:
            frame = frame[frame["discontinued"] == 0]
        return top_products_figure(frame, measure, top)

    def reorder_due(self):
        """
        "Buy it again": this customer's products that are due another order (see
        analytics.reorder_due), most overdue first, as a list of dicts (empty when
        no product has been bought on three different orders).
        """
        return reorder_due(self._order_lines_frame())

    @classmethod
    def search(cls, company_name="", contact_name="", contact_title="", city="", country=""):
        """
        Filters customers by any combination of company name, contact name,
        contact title, city and country (every customer when none are given), for
        customer_list's search form. A @classmethod because it builds a new
        queryset from the class (cls) rather than acting on one Customer. The two
        free-text fields use "icontains" (case-insensitive substring); the others
        come from dropdowns, so they match exactly.
        """
        queryset = cls.objects.order_by("company_name")
        if company_name:
            queryset = queryset.filter(company_name__icontains=company_name)
        if contact_name:
            queryset = queryset.filter(contact_name__icontains=contact_name)
        if contact_title:
            queryset = queryset.filter(contact_title=contact_title)
        if city:
            queryset = queryset.filter(city=city)
        if country:
            queryset = queryset.filter(country=country)
        return queryset

    @classmethod
    def authenticate(cls, customer_id, password):
        """
        Checks a login: the customer with this ID, and a direct compare of the
        password column (unlike Employee, which has no password column). Returns
        the Customer on success, None otherwise.
        """
        customer = cls.objects.filter(pk=customer_id).first()
        if customer is None:
            return None
        if customer.password != password:
            return None
        return customer

    @classmethod
    def generate_customer_id(cls, company_name):
        """
        Builds a new, unique 5-letter customer_id from a company name, in the
        existing style ("Alfreds Futterkiste" -> ALFKI). Called by
        customer_create after the form validates; a customer never types an ID.
        It takes the name's first five letters (padded with "X"), and if that ID is
        taken, swaps in a trailing counter (ALFK1, ALFK2, ...). The primary key's own
        uniqueness is the final guarantee; the loop just avoids a rejected insert.
        """
        letters = "".join(char for char in company_name.upper() if char.isalpha())
        base = (letters + "XXXXX")[:5]

        if not cls.objects.filter(pk=base).exists():
            return base

        # base alone is taken: replace its trailing characters with a counter.
        suffix = 1
        while suffix < 100_000:
            digits = str(suffix)
            candidate = base[: 5 - len(digits)] + digits
            if not cls.objects.filter(pk=candidate).exists():
                return candidate
            suffix += 1

        # Practically unreachable for a dataset this size.
        raise ValueError(f"Could not generate a unique customer_id from {company_name!r}")

    class Meta:
        managed = False
        db_table = 'customers'


class Employee(models.Model):
    """A DjangoTraders employee. Has a self-referencing FK for its manager (reports_to)."""
    employee_id = models.SmallIntegerField(primary_key=True)
    last_name = models.CharField(max_length=20)
    first_name = models.CharField(max_length=10)
    title = models.CharField(max_length=30, blank=True, null=True)
    title_of_courtesy = models.CharField(max_length=25, blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    hire_date = models.DateField(blank=True, null=True)
    address = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=15, blank=True, null=True)
    region = models.CharField(max_length=15, blank=True, null=True)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=15, blank=True, null=True)
    home_phone = models.CharField(max_length=24, blank=True, null=True)
    extension = models.CharField(max_length=4, blank=True, null=True)
    photo = models.BinaryField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    photo_path = models.CharField(max_length=255, blank=True, null=True)
    # region [CONCEPT] self-referencing FK (reports_to)
    # FK to Employee itself, for the manager hierarchy: gives us
    # employee.reports_to.first_name (up to the manager) and
    # employee.employee_set.all() (down to their reports).
    # SET_NULL so deleting a manager just clears the link, not their reports.
    # endregion
    reports_to = models.ForeignKey('self', models.SET_NULL, db_column='reports_to', blank=True, null=True)

    @property
    def formatted_address(self):
        """This employee's address fields joined into one line, blanks skipped."""
        parts = [self.address, self.city, self.region, self.postal_code, self.country]
        return ", ".join(part for part in parts if part)

    @property
    def is_manager(self):
        """
        True when at least one employee reports to this one. A manager may open
        any employee's page; employee_set is the reverse side of reports_to
        (every employee whose manager is this one).
        """
        return self.employee_set.exists()

    def _order_lines_frame(self):
        """Every line on the placed orders this employee handled, as a DataFrame (see lines_frame in charts.py)."""
        return lines_frame(OrderDetail.objects.filter(
            order__employee=self, order__order_date__isnull=False
        ))

    def revenue_years(self):
        """The years in which this employee handled placed orders, oldest first (for the year dropdown)."""
        frame = self._order_lines_frame()
        if frame.empty:
            return []
        return sorted(int(year) for year in frame["year"].unique())

    def revenue_over_time(self, level="year", year=None, height=360):
        """
        The dashboard's revenue-over-time chart, as chart HTML (None when this
        employee has no orders). Each bar's hover shows the period, its revenue
        and its number of orders.

        level "year": one bar per year (year is ignored).
        level "month" with a year: the twelve months of that year, as a line chart.
        level "month" with year=None: every month from the first order to the last,
        across all years, as a line chart, so it reads as revenue over time.

        Orders are distinct orders. Months with no orders are filled in with zero
        (reindex over a full period range), so a quiet month shows as an empty
        slot instead of vanishing.
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        if level == "year":
            grouped = frame.groupby("year").agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"))
            table = grouped.reset_index()
            table["label"] = table["year"].astype(str)
            table["full_label"] = table["label"]
            title, axis = "Revenue by year", "Year"
        else:
            if year is not None:
                frame = frame[frame["year"] == year]
            frame = frame.assign(period=frame["order_date"].dt.to_period("M"))
            grouped = frame.groupby("period").agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"))
            if year is None:
                full_range = pd.period_range(grouped.index.min(), grouped.index.max(), freq="M")
                title = "Revenue by month, all years"
            else:
                full_range = pd.period_range(f"{year}-01", f"{year}-12", freq="M")
                title = f"Revenue by month, {year}"
            grouped = grouped.reindex(full_range, fill_value=0)
            table = grouped.reset_index(names="period")
            table["label"] = table["period"].dt.strftime("%b" if year is not None else "%b %Y")
            table["full_label"] = table["period"].dt.strftime("%B %Y")
            axis = "Month"
        hover = [
            f"<b>{row.full_label}</b><br>Revenue: ${row.revenue:,.0f}<br>Orders: {row.orders:,}"
            for row in table.itertuples()
        ]
        labels = {"label": axis, "revenue": "Revenue ($)"}
        if level == "year":
            return bar_figure(table, "label", "revenue", title, labels, height=height, hover=hover)
        # Months run in time order, so a line reads better than bars.
        return line_figure(table, "label", "revenue", title, labels, height=height, hover=hover)

    def period_detail(self, key):
        """
        What the Details modal shows for one period of this employee's orders: key
        is "1997" (a year) or "1997-03" (a month). Returns a dict with label,
        revenue, orders and products (the five products with the most revenue in
        that period, each with units and revenue). For a whole year it also returns
        months_plot, that year's revenue by month; for a single month it is None.
        The view has already checked that key is a real period.
        """
        year, _, month = key.partition("-")
        frame = self._order_lines_frame()
        in_period = frame["year"] == int(year)
        label = year
        if month:
            in_period &= frame["month"] == int(month)
            label = pd.Timestamp(year=int(year), month=int(month), day=1).strftime("%B %Y")
        part = frame[in_period]
        products = (
            part.groupby("product_name", as_index=False)
            .agg(units=("quantity", "sum"), revenue=("revenue", "sum"))
            .sort_values("revenue", ascending=False).head(5)
        )
        months_plot = None
        if not month:
            months_plot = self.revenue_over_time("month", int(year), height=300)
        return {
            "label": label,
            "revenue": part["revenue"].sum(),
            "orders": part["order_id"].nunique(),
            "products": products.to_dict("records"),
            "months_plot": months_plot,
        }

    @classmethod
    def _performance_frame(cls):
        """
        One row per employee who handled at least one placed order:
        revenue, orders (distinct orders), customers (distinct customers),
        average_order, revenue_per_customer, share (percent of all company
        revenue), and a rank for each measure (revenue_rank, orders_rank,
        average_order_rank, customers_rank, revenue_per_customer_rank;
        1 = best, ties share a rank). The database does the grouping with
        values()/annotate(); pandas adds the derived columns. Sorted by
        revenue_rank. The base for performance(), team_comparison() and
        leaderboard().
        """
        rows = (
            OrderDetail.objects.filter(order__order_date__isnull=False)
            .values(employee_key=F("order__employee_id"))
            .annotate(
                revenue=Sum(Supplier._line_revenue()),
                orders=Count("order", distinct=True),
                customers=Count("order__customer", distinct=True),
            )
        )
        frame = pd.DataFrame(list(rows)).dropna(subset=["employee_key"]) if rows else pd.DataFrame()
        if frame.empty:
            return frame
        frame["employee_key"] = frame["employee_key"].astype(int)
        frame["average_order"] = frame["revenue"] / frame["orders"]
        frame["revenue_per_customer"] = frame["revenue"] / frame["customers"].where(frame["customers"] > 0)
        frame["share"] = frame["revenue"] / frame["revenue"].sum() * 100
        for measure in ("revenue", "orders", "average_order", "customers", "revenue_per_customer"):
            frame[f"{measure}_rank"] = frame[measure].rank(ascending=False, method="min")
        return frame.sort_values("revenue_rank")

    def performance(self):
        """
        This employee compared with the other employees, for the
        dashboard's summary tiles: a dict with their revenue, orders,
        average_order, share of company revenue, revenue_rank and
        orders_rank, employee_count (how many employees have orders),
        colleagues_behind, team_share (an even split, 100 / employee_count),
        team_average_order (the mean of the employees' average orders, the same
        figure the "vs. the team" table shows) and
        average_order_diff (percent above or below that team figure).
        Returns None when this employee has no placed orders.
        """
        frame = self._performance_frame()
        if frame.empty:
            return None
        mine = frame[frame["employee_key"] == self.employee_id]
        if mine.empty:
            return None
        row = mine.iloc[0]
        count = len(frame)
        team_average_order = frame["average_order"].mean()
        return {
            "revenue": row["revenue"],
            "orders": int(row["orders"]),
            "average_order": row["average_order"],
            "share": row["share"],
            "revenue_rank": int(row["revenue_rank"]),
            "orders_rank": int(row["orders_rank"]),
            "employee_count": count,
            "colleagues_behind": count - int(row["revenue_rank"]),
            "team_share": 100 / count,
            "team_average_order": team_average_order,
            "average_order_diff": (row["average_order"] / team_average_order - 1) * 100,
        }

    # What the team comparison chart's dropdown can compare: the key and its label.
    TEAM_MEASURES = {
        "revenue": "Revenue",
        "orders": "Orders",
        "customers": "Customers served",
    }

    def team_comparison(self):
        """
        This employee against the team on the three TEAM_MEASURES, as a list of
        dicts for the dashboard's comparison table and chart: measure, label, kind
        ("money" or "count", for formatting), you, team_average (the mean across
        employees), vs_average (you as a percent above or below that average), best
        (the highest employee, nameless), rank and employee_count.
        Returns [] when this employee has no placed orders.
        """
        frame = self._performance_frame()
        mine = frame[frame["employee_key"] == self.employee_id] if not frame.empty else frame
        if mine.empty:
            return []
        row = mine.iloc[0]
        comparison = []
        for measure, label in self.TEAM_MEASURES.items():
            team_average = frame[measure].mean()
            comparison.append({
                "measure": measure,
                "label": label,
                "kind": "money" if measure == "revenue" else "count",
                "you": row[measure],
                "team_average": team_average,
                "vs_average": (row[measure] / team_average - 1) * 100,
                "best": frame[measure].max(),
                "rank": int(row[f"{measure}_rank"]),
                "employee_count": len(frame),
            })
        return comparison

    def team_comparison_plot(self, measure="revenue", you_label="You"):
        """
        Bar chart for one measure (a TEAM_MEASURES key): this employee, the team
        average and the best employee, in real units. The best bar is nameless.
        This one is built with Plotly's graph_objects (go) rather than Express, so
        each bar is added by hand. Returns None when there is nothing to compare.
        """
        row = next((r for r in self.team_comparison() if r["measure"] == measure), None)
        if row is None:
            return None

        names = [you_label, "Team average", "Best"]
        values = [row["you"], row["team_average"], row["best"]]
        is_money = row["kind"] == "money"
        text = [f"${v:,.0f}" if is_money else f"{v:,.0f}" for v in values]

        figure = go.Figure(go.Bar(
            x=names, y=values, text=text, textposition="outside", cliponaxis=False,
            marker_color=[CHART_COLORS[0], "#5f6b76", CHART_COLORS[2]],
            hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
        ))
        figure.update_layout(
            title=f"{row['label']}: {you_label} compared with the team", height=340,
            yaxis_title="Revenue ($)" if is_money else row["label"],
        )
        figure.update_yaxes(range=[0, max(values) * 1.25])
        return figure_html(figure)

    def leaderboard(self):
        """
        Every employee ranked by revenue, as a list of dicts for the
        manager-only leaderboard table: rank, name, orders, revenue,
        average_order, share, is_self (True on this page's employee).
        Names and dollars for every employee, so the view only calls
        this for a manager; everyone else gets team_comparison(), which
        shows averages and a nameless best instead of other people.
        """
        frame = self._performance_frame()
        if frame.empty:
            return []
        names = {e.employee_id: f"{e.first_name} {e.last_name}" for e in Employee.objects.all()}
        return [
            {
                "rank": int(row.revenue_rank),
                "name": names.get(row.employee_key, "Unknown"),
                "orders": row.orders,
                "revenue": row.revenue,
                "average_order": row.average_order,
                "share": row.share,
                "is_self": row.employee_key == self.employee_id,
            }
            for row in frame.itertuples()
        ]

    def customer_revenue_plot(self, top=10, kind="bar"):
        """
        Revenue on this employee's orders by customer, as kind="bar" (horizontal bars,
        largest at the top; the default), "column" (vertical bars, largest first) or
        "pie". top=10 keeps the ten biggest customers and top=None charts every
        customer; each bar is labeled with its dollars and the percentage of this
        employee's total revenue (all customers, not just the ones charted). A pie
        shows each customer's share, the largest ten at most plus the rest as "Other".
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        by_customer = (
            frame.groupby("customer_name", as_index=False)["revenue"].sum()
            .sort_values("revenue")
        )
        total = by_customer["revenue"].sum()
        if kind == "pie":
            slices = top_with_other(by_customer, "customer_name", "revenue", min(top or 10, 10))
            return pie_figure(slices, "customer_name", "revenue", "Share of revenue by customer",
                              color_names=frame["customer_name"])
        if top:
            by_customer = by_customer.tail(top)
        # Horizontal bars list the largest at the top; columns run largest first, left to right.
        horizontal = kind != "column"
        if not horizontal:
            by_customer = by_customer.iloc[::-1]
        text = [f"${row.revenue:,.0f} ({row.revenue / total * 100:.1f}%)" for row in by_customer.itertuples()]
        # Same sizing rule as revenue_breakdown_plot, so the two charts sharing a dashboard row match.
        per_bar = 32 if len(by_customer) <= 12 else 24
        return bar_figure(
            by_customer, "customer_name", "revenue",
            f"Top {top} customers by revenue" if top else "Revenue by customer",
            {"customer_name": "Customer", "revenue": "Revenue ($)"},
            color_names=frame["customer_name"], horizontal=horizontal,
            height=max(420, per_bar * len(by_customer) + 100) if horizontal else 420, trend=False, text=text,
        )

    def category_mix_plot(self, you_label="You"):
        """
        Revenue by category as a share of revenue, this employee beside the whole
        team: grouped bars, two per category. The employee's bars are each category's
        percent of THEIR OWN revenue; the team's bars are each category's percent of
        ALL employees' combined revenue. Each set adds up to 100. None when this
        employee has no placed orders.

        The team figure is one combined aggregate: it is grouped by category in the
        database, so no employee id, name or per-employee amount ever reaches this
        method, the chart or the page.
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        mine = frame.groupby("category_name")["revenue"].sum()

        rows = (
            OrderDetail.objects.filter(order__order_date__isnull=False, order__employee__isnull=False)
            .values(category_name=F("product__category__category_name"))
            .annotate(revenue=Sum(Supplier._line_revenue()))
        )
        team = pd.DataFrame(list(rows))
        team["category_name"] = team["category_name"].fillna("Uncategorized")
        team = team.groupby("category_name")["revenue"].sum()

        mix = pd.DataFrame({"you": mine, "team": team}).fillna(0)
        mix["you"] = mix["you"] / mix["you"].sum() * 100
        mix["team"] = mix["team"] / mix["team"].sum() * 100
        mix = mix.sort_values(["you", "team"], ascending=False)

        figure = go.Figure()
        figure.add_bar(
            name=you_label, x=list(mix.index), y=list(mix["you"]), marker_color=CHART_COLORS[0],
            text=[f"{v:.1f}%" for v in mix["you"]], textposition="outside", cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>%{text} of " + ("your" if you_label == "You" else f"{you_label}'s") + " revenue<extra></extra>",
        )
        figure.add_bar(
            name="Whole team", x=list(mix.index), y=list(mix["team"]), marker_color="#5f6b76",
            text=[f"{v:.1f}%" for v in mix["team"]], textposition="outside", cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>%{text} of the team's combined revenue<extra></extra>",
        )
        figure.update_layout(
            barmode="group", bargap=0.25, height=420, title="Revenue mix by category",
            yaxis_title="Share of revenue (%)", legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "right", "x": 1.0},
        )
        figure.update_yaxes(range=[0, max(mix["you"].max(), mix["team"].max()) * 1.25])
        figure.update_xaxes(type="category")
        return figure_html(figure)

    def reorder_opportunities(self, limit=15):
        """
        "Buy it again" for an employee: products their own customers usually reorder
        that are due (analytics.reorder_due), biggest revenue at stake first. Built only
        from the lines on orders THIS employee handled, so it never involves a customer
        or an order someone else handled.
        """
        due = reorder_due(self._order_lines_frame())
        return sorted(due, key=lambda row: row["revenue_at_stake"], reverse=True)[:limit]

    # What the dashboard's "Revenue by" dropdown can group by: the key, the
    # singular word used in chart titles, and the OrderDetail field to group on.
    BREAKDOWNS = {
        "supplier": ("supplier", "product__supplier__company_name"),
        "product": ("product", "product__product_name"),
        "category": ("category", "product__category__category_name"),
    }

    def revenue_breakdown_plot(self, by="supplier", all_orders=False, top=None, kind="bar"):
        """
        Horizontal bar chart of revenue by supplier, product or category
        (by = "supplier", "product" or "category"), largest at the top. What it
        shows depends on who is looking (the view passes
        all_orders=viewer.is_manager):

        all_orders=True (a manager): each group's revenue across every placed
        order, labeled with its dollars and its percentage of all revenue.

        all_orders=False (anyone else): the share of each group's revenue that came
        from this employee's own orders, as a percentage. Only the percentage is
        charted, never the group's total, so an employee sees what they brought in
        without seeing what the group earns overall.

        top limits the chart to the largest N bars; None shows every group. Colors
        come from the full list of groups, so a group keeps its color whichever top
        is chosen. The rows are grouped in the database with values()/annotate().

        kind is "bar" (horizontal, the default), "column" (vertical) or "pie". A pie is
        for a manager only, because an employee's bars are shares of different totals
        that don't add up to a whole; it shows each group's share of all revenue, the
        largest ten at most plus the rest as "Other".
        """
        word, field = self.BREAKDOWNS[by]
        placed = OrderDetail.objects.filter(order__order_date__isnull=False)
        revenue = Sum(Supplier._line_revenue())

        def revenue_by_group(lines):
            rows = lines.values(group_name=F(field)).annotate(revenue=revenue)
            frame = pd.DataFrame(list(rows))
            if frame.empty:
                return frame
            frame["group_name"] = frame["group_name"].fillna(f"Unknown {word}")
            return frame.groupby("group_name", as_index=False)["revenue"].sum()

        totals = revenue_by_group(placed)
        if totals.empty:
            return None

        if all_orders:
            chart_data = totals.copy()
            chart_data["percent"] = chart_data["revenue"] / chart_data["revenue"].sum() * 100
            chart_data = chart_data.sort_values("revenue", ascending=False)
            value, title = "revenue", f"Revenue by {word} (all orders)"
            labels = {"group_name": word.capitalize(), "revenue": "Revenue ($)"}
        else:
            mine = revenue_by_group(placed.filter(order__employee=self))
            chart_data = totals.merge(mine, on="group_name", how="left", suffixes=("_all", "_mine"))
            chart_data["revenue_mine"] = chart_data["revenue_mine"].fillna(0)
            chart_data = chart_data[chart_data["revenue_all"] > 0]
            chart_data["share"] = chart_data["revenue_mine"] / chart_data["revenue_all"] * 100
            chart_data["percent"] = chart_data["share"]
            chart_data = chart_data.sort_values("share", ascending=False)
            value, title = "share", f"Your share of each {word}'s revenue (%)"
            labels = {"group_name": word.capitalize(), "share": f"Share of {word} revenue (%)"}

        if kind == "pie" and all_orders:
            slices = top_with_other(chart_data, "group_name", "revenue", min(top or 10, 10))
            return pie_figure(slices, "group_name", "revenue", f"Share of revenue by {word}",
                              color_names=totals["group_name"])

        if top:
            chart_data = chart_data.head(top)
            title = f"{title} -- top {top}"
        # Plotly draws the first horizontal bar at the bottom, so bars flip to put the largest
        # on top; columns already run largest first, left to right.
        horizontal = kind != "column"
        if horizontal:
            chart_data = chart_data.iloc[::-1]

        if all_orders:
            text = [f"${row.revenue:,.0f} ({row.percent:.1f}%)" for row in chart_data.itertuples()]
        else:
            text = [f"{row.percent:.1f}%" for row in chart_data.itertuples()]

        per_bar = 32 if len(chart_data) <= 12 else 24
        return bar_figure(
            chart_data, "group_name", value, title, labels,
            color_names=totals["group_name"], horizontal=horizontal,
            height=max(420, per_bar * len(chart_data) + 100) if horizontal else 420, trend=False, text=text,
        )

    @classmethod
    def authenticate(cls, employee_id, password):
        """
        Looks up the employee picked in the login form and checks their
        password: the 4-digit year of their own birth_date, as a string
        (e.g. birth_date of 1985-03-12 -> password "1985"). Returns the
        matching Employee on success, or None if the employee_id doesn't
        exist, has no birth_date on record, or the password is wrong.
        """
        employee = cls.objects.filter(pk=employee_id).first()
        if employee is None or employee.birth_date is None:
            return None
        if str(employee.birth_date.year) != password:
            return None
        return employee

    class Meta:
        managed = False
        db_table = 'employees'


class OrderDetail(models.Model):
    """
    A single line item on an order (composite primary key: order_id + product_id).
    """
    # region [WARNING] order+product form the composite PK, not a separate id column
    # order and product below are ordinary FKs, but they're ALSO the two
    # columns making up this table's primary key (CompositePrimaryKey, not
    # a separate id column) - a product can only appear once per order.
    # endregion
    pk = models.CompositePrimaryKey('order_id', 'product_id')

    # FK to Order (order_detail.order.order_date, order.orderdetail_set.all()).
    # CASCADE: a line item is meaningless without its order.
    order = models.ForeignKey('Order', models.CASCADE)

    # FK to Product (order_detail.product.product_name, product.orderdetail_set.all()).
    # PROTECT: refuse to delete a product still on a historical order line.
    product = models.ForeignKey('Product', models.PROTECT)
    unit_price = models.FloatField()
    quantity = models.SmallIntegerField()
    discount = models.FloatField()

    @property
    def line_total(self):
        """
        This line's own revenue: unit_price times quantity, minus the
        discount fraction. A @property, not a field, since it's derived
        from the three fields above rather than stored -- Order.order_total
        sums this same property across every line instead of repeating
        the formula.
        """
        return self.unit_price * self.quantity * (1 - self.discount)

    class Meta:
        managed = False
        db_table = 'order_details'


class Order(models.Model):
    """
    A customer order. The customer/employee/shipper links are all nullable, so
    on_delete=SET_NULL keeps the order history intact even if one of those
    related records is later removed.
    """
    # region [WHY] AutoField only for order_id
    # SmallAutoField, unlike this app's other primary keys: order_id's
    # database column is backed by a real auto-incrementing sequence, so
    # the other models' IDs (category_id, etc.) aren't - they're fixed
    # reference IDs the database won't generate for you.
    # endregion
    order_id = models.SmallAutoField(primary_key=True)
    order_date = models.DateField(blank=True, null=True)
    required_date = models.DateField(blank=True, null=True)
    shipped_date = models.DateField(blank=True, null=True)
    freight = models.FloatField(blank=True, null=True)
    ship_name = models.CharField(max_length=40, blank=True, null=True)
    ship_address = models.CharField(max_length=60, blank=True, null=True)
    ship_city = models.CharField(max_length=15, blank=True, null=True)
    ship_region = models.CharField(max_length=15, blank=True, null=True)
    ship_postal_code = models.CharField(max_length=10, blank=True, null=True)
    ship_country = models.CharField(max_length=15, blank=True, null=True)

    # FK to Customer (order.customer.company_name, customer.order_set.all()).
    customer = models.ForeignKey(Customer, models.SET_NULL, blank=True, null=True)

    # FK to Employee (order.employee.last_name, employee.order_set.all()).
    employee = models.ForeignKey(Employee, models.SET_NULL, blank=True, null=True)

    # FK to Shipper, stored in a column named ship_via (db_column below) --
    # that's the existing table's column name, not shipper_id.
    ship_via = models.ForeignKey('Shipper', models.SET_NULL, db_column='ship_via', blank=True, null=True)

    @property
    def order_total(self):
        """This order's total: every line item's line_total (OrderDetail.line_total) added together."""
        return sum(line.line_total for line in self.orderdetail_set.all())

    @property
    def formatted_ship_address(self):
        """This order's ship_* address fields joined into one line, blanks skipped."""
        parts = [self.ship_address, self.ship_city, self.ship_region, self.ship_postal_code, self.ship_country]
        return ", ".join(part for part in parts if part)

    class Meta:
        managed = False
        db_table = 'orders'


class Product(models.Model):
    """
    A DjangoTraders product. Supplier and category are both nullable, so removing
    either one just clears the link (SET_NULL) instead of touching the product.
    """
    product_id = models.SmallIntegerField(primary_key=True)
    product_name = models.CharField(max_length=40)
    quantity_per_unit = models.CharField(max_length=20, blank=True, null=True)
    unit_price = models.FloatField(blank=True, null=True)
    units_in_stock = models.SmallIntegerField(blank=True, null=True)
    units_on_order = models.SmallIntegerField(blank=True, null=True)
    reorder_level = models.SmallIntegerField(blank=True, null=True)
    discontinued = models.IntegerField()
    date_discontinued = models.DateField(blank=True, null=True)

    # FK to Supplier (product.supplier.company_name, supplier.product_set.all()).
    supplier = models.ForeignKey('Supplier', models.SET_NULL, blank=True, null=True)

    # FK to Category (product.category.category_name, category.product_set.all()).
    category = models.ForeignKey(Category, models.SET_NULL, blank=True, null=True)

    @property
    def is_discontinued(self):
        """discontinued is a plain 1/0 column; this maps it to a real bool. A @property is computed on each access, so it needs no migration."""
        return bool(self.discontinued)

    @classmethod
    def search(cls, product_name="", category_id="", show_all=False):
        """
        Filters products by an optional name (case-insensitive substring) and
        category (exact, since it comes from a dropdown), for product_list's search
        form. Discontinued products are left out unless show_all is True; the
        filter uses the raw 1/0 column, because the database can't filter on the
        is_discontinued property.
        """
        queryset = cls.objects.order_by("product_name")
        if product_name:
            queryset = queryset.filter(product_name__icontains=product_name)

        if category_id:
            queryset = queryset.filter(category_id=category_id)

        if not show_all:
            queryset = queryset.filter(discontinued=0)

        return queryset

    @property
    def total_revenue(self):
        """Total revenue from this product: every line it appears on, each line_total added together (orderdetail_set is the reverse side of OrderDetail.product)."""
        return sum(line.line_total for line in self.orderdetail_set.all())

    @property
    def units_sold(self):
        """Total quantity of this product sold, across every order line it appears on."""
        return sum(line.quantity for line in self.orderdetail_set.all())

    class Meta:
        managed = False
        db_table = 'products'


class Shipper(models.Model):
    """A shipping carrier. No foreign keys."""
    shipper_id = models.SmallIntegerField(primary_key=True)
    company_name = models.CharField(max_length=40)
    phone = models.CharField(max_length=24, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'shippers'


class Supplier(models.Model):
    """A product supplier. No foreign keys."""
    supplier_id = models.SmallIntegerField(primary_key=True)
    company_name = models.CharField(max_length=40)
    contact_name = models.CharField(max_length=30, blank=True, null=True)
    contact_title = models.CharField(max_length=30, blank=True, null=True)
    address = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=15, blank=True, null=True)
    region = models.CharField(max_length=15, blank=True, null=True)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=15, blank=True, null=True)
    phone = models.CharField(max_length=24, blank=True, null=True)
    fax = models.CharField(max_length=24, blank=True, null=True)
    homepage = models.TextField(blank=True, null=True)

    # region [WHY] a fixed shared password for suppliers
    # The suppliers table has no password column, and this app's tables are unmanaged,
    # so there is nowhere to store one per supplier. Every supplier logs in with this
    # one demo password. A real app would store a hashed password per supplier.
    # endregion
    SHARED_PASSWORD = "pass"

    @classmethod
    def authenticate(cls, supplier_id, password):
        """Checks a login: the supplier picked in the dropdown and the shared password. An unknown or non-numeric supplier_id is a failed login, not a crash."""
        try:
            supplier = cls.objects.filter(pk=int(supplier_id)).first()
        except (TypeError, ValueError):
            return None
        if supplier is None or password != cls.SHARED_PASSWORD:
            return None
        return supplier

    @property
    def formatted_address(self):
        """Address, city, region, postal_code, and country joined into one line (blank ones skipped)."""
        parts = [self.address, self.city, self.region, self.postal_code, self.country]
        return ", ".join(part for part in parts if part)

    def _placed_lines(self):
        """Every line on a placed order for one of this supplier's products (product__supplier=self follows OrderDetail -> Product -> Supplier in one query)."""
        return OrderDetail.objects.filter(
            product__supplier=self, order__order_date__isnull=False
        )

    @staticmethod
    def _line_revenue():
        """The database-side version of OrderDetail.line_total, for Sum(): unit_price * quantity * (1 - discount)."""
        return ExpressionWrapper(
            F("unit_price") * F("quantity") * (1 - F("discount")),
            output_field=FloatField(),
        )

    def summary(self):
        """Headline numbers for the Info tab: products, units sold, revenue, orders (revenue and units from placed orders only)."""
        totals = self._placed_lines().aggregate(
            units=Sum("quantity"),
            revenue=Sum(self._line_revenue()),
            orders=Count("order_id", distinct=True),
        )
        return {
            "product_count": self.product_set.count(),
            "units": totals["units"] or 0,
            "revenue": totals["revenue"] or 0,
            "orders": totals["orders"],
        }

    def order_history(self):
        """
        One row per placed order that includes at least one of this
        supplier's products, newest first: order_id, order_date, the
        customer's company name, how many of this supplier's products
        were on the order, and the units and revenue for those lines
        only -- never the rest of the order, which belongs to other
        suppliers too. values() picks the columns to group by and
        annotate() adds the per-group totals.
        """
        return (
            self._placed_lines()
            .values("order_id", "order__order_date", "order__customer__company_name")
            .annotate(
                products=Count("product_id", distinct=True),
                units=Sum("quantity"),
                revenue=Sum(self._line_revenue()),
            )
            .order_by("-order__order_date", "-order_id")
        )

    def product_revenue(self):
        """
        One row per product this supplier provides (including products
        with no sales yet, shown as zeros), largest revenue first:
        product_id, product_name, category_name, units, revenue, orders.
        """
        sales = {
            row["product_id"]: row
            for row in self._placed_lines()
            .values("product_id")
            .annotate(
                units=Sum("quantity"),
                revenue=Sum(self._line_revenue()),
                orders=Count("order_id", distinct=True),
            )
        }
        rows = []
        for product in self.product_set.select_related("category"):
            sold = sales.get(product.product_id, {})
            rows.append({
                "product_id": product.product_id,
                "product_name": product.product_name,
                "category_name": product.category.category_name if product.category else "—",
                "units": sold.get("units", 0),
                "revenue": sold.get("revenue", 0),
                "orders": sold.get("orders", 0),
            })
        return sorted(rows, key=lambda row: row["revenue"], reverse=True)

    # region [WHY] the dashboard methods repeat the customer's, with a different scope
    # Everything below starts from _order_lines_frame(), the frame of this supplier's
    # own placed lines (product__supplier=self), and hands it to the same chart
    # builders in charts.py that the customer dashboard uses.
    # endregion
    def _order_lines_frame(self):
        """Every placed order line for this supplier's own products as a DataFrame (see lines_frame in charts.py)."""
        return lines_frame(self._placed_lines())

    def order_years(self):
        """Distinct years this supplier's products were ordered in, newest first."""
        frame = self._order_lines_frame()
        if frame.empty:
            return []
        return sorted((int(year) for year in frame["year"].unique()), reverse=True)

    def dashboard_stats(self):
        """The four summary tiles' numbers (Total Revenue with its year-to-date change, Orders, Units Sold, Last Order) as one dict (analytics.summary_stats)."""
        return summary_stats(self._order_lines_frame())

    def annual_orders_plot(self):
        """Bar chart of this supplier's revenue for each year, with a trend line."""
        return annual_revenue_figure(self._order_lines_frame())

    def orders_placed_plot(self, year):
        """Bar chart of this supplier's revenue for each of the twelve months of one year (what the year dropdown loads); None when that year has no orders."""
        return monthly_revenue_figure(self._order_lines_frame(), year)

    def category_revenue_plot(self, top=None, year=None):
        """Revenue by category for this supplier's products: the largest N (None = all), one year or all years."""
        return category_revenue_figure(filter_year(self._order_lines_frame(), year), top)

    def unit_share_plot(self, top=None, year=None, kind="pie"):
        """Each category's share of the units sold, as a "pie" or as percent "bar"s."""
        return unit_share_figure(filter_year(self._order_lines_frame(), year), top, kind)

    def top_products_plot(self, measure="revenue", top=10):
        """This supplier's top N products by "revenue" or "units" (None = all)."""
        return top_products_figure(self._order_lines_frame(), measure, top)

    def top_customers(self, top=10):
        """
        The customers who bought this supplier's products, biggest first, as a list
        of dicts: customer (company name), orders and revenue (on this supplier's lines
        only) and share (percent of this supplier's revenue). Nothing about what else
        those customers buy: the frame holds only this supplier's lines.
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return []
        by_customer = (
            frame.groupby("customer_name")
            .agg(orders=("order_id", "nunique"), revenue=("revenue", "sum"))
            .sort_values("revenue", ascending=False)
        )
        total = by_customer["revenue"].sum()
        shown = by_customer.head(top) if top else by_customer
        return [
            {"customer": name, "orders": int(row.orders), "revenue": float(row.revenue), "share": row.revenue / total * 100}
            for name, row in shown.iterrows()
        ]

    # What the comparison chart's dropdown can compare: the key and its label.
    COMPARE_MEASURES = {
        "revenue": "Revenue",
        "orders": "Orders",
        "units": "Units sold",
        "customers": "Customers served",
    }

    @classmethod
    def _comparison_frame(cls):
        """One row per supplier with sales: revenue, orders, units and customers. Used only inside comparison(); it holds every supplier's id, so it never leaves this module's methods."""
        rows = (
            OrderDetail.objects.filter(order__order_date__isnull=False, product__supplier__isnull=False)
            .values(supplier_key=F("product__supplier_id"))
            .annotate(
                revenue=Sum(cls._line_revenue()),
                orders=Count("order", distinct=True),
                units=Sum("quantity"),
                customers=Count("order__customer", distinct=True),
            )
        )
        return pd.DataFrame(list(rows))

    def comparison(self):
        """
        This supplier against ALL suppliers on each COMPARE_MEASURES measure, as a list
        of dicts: measure, label, kind ("money" or "count"), you, average (the mean
        across suppliers with sales), vs_average (percent above or below it) and best
        (the highest supplier, as a plain number). Only numbers leave this method: the
        best is frame[measure].max(), never a row, so no other supplier's name or id can
        reach the page. [] when this supplier has no sales.
        """
        frame = self._comparison_frame()
        if frame.empty:
            return []
        mine = frame[frame["supplier_key"] == self.supplier_id]
        if mine.empty:
            return []
        row = mine.iloc[0]
        comparison = []
        for measure, label in self.COMPARE_MEASURES.items():
            average = float(frame[measure].mean())
            comparison.append({
                "measure": measure,
                "label": label,
                "kind": "money" if measure == "revenue" else "count",
                "you": float(row[measure]),
                "average": average,
                "vs_average": (float(row[measure]) / average - 1) * 100 if average else None,
                "best": float(frame[measure].max()),
            })
        return comparison

    def comparison_plot(self, measure="revenue"):
        """Bar chart for one COMPARE_MEASURES measure: this supplier, the average of all suppliers and the best supplier (nameless), in real units. None with no sales."""
        row = next((r for r in self.comparison() if r["measure"] == measure), None)
        if row is None:
            return None
        names = ["You", "Average supplier", "Best supplier"]
        values = [row["you"], row["average"], row["best"]]
        is_money = row["kind"] == "money"
        text = [f"${v:,.0f}" if is_money else f"{v:,.0f}" for v in values]
        figure = go.Figure(go.Bar(
            x=names, y=values, text=text, textposition="outside", cliponaxis=False,
            marker_color=[CHART_COLORS[0], "#5f6b76", CHART_COLORS[2]],
            hovertemplate="<b>%{x}</b><br>%{text}<extra></extra>",
        ))
        figure.update_layout(
            title=f"{row['label']}: you compared with all suppliers", height=340,
            yaxis_title="Revenue ($)" if is_money else row["label"],
        )
        figure.update_yaxes(range=[0, max(values) * 1.25])
        return figure_html(figure)

    def default_share_years(self):
        """(start, end) for the share-change chart: the newest year with orders and the one before it, or None when there are fewer than two years."""
        years = self.order_years()
        return (years[1], years[0]) if len(years) >= 2 else None

    def share_change_plot(self, start, end):
        """Which of this supplier's products gained or lost share of its revenue between two years (a diverging bar chart; see charts.share_change_figure)."""
        return share_change_figure(self._order_lines_frame(), start, end)

    def pattern_plot(self, measure="revenue", view="amount"):
        """A year-by-month heatmap of this supplier's revenue, units or orders, as real amounts or as each month's percent of its year (charts.month_pattern_figure)."""
        return month_pattern_figure(self._order_lines_frame(), measure, view)

    class Meta:
        managed = False
        db_table = 'suppliers'