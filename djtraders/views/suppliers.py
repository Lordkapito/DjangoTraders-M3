"""
Supplier pages: the page shell, its four tabs (Dashboard, Info, Order History,
Product Revenue), the AJAX charts behind the dashboard's controls, and the supplier
login. A supplier sees only their own page; employees
may open any (see supplier_access_denied in access.py).
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from ..models import Supplier
from .access import supplier_access_denied
from .chart_params import read_choice, read_top, read_year


def supplier_login_view(request):
    """
    Supplier login: pick a company from a dropdown and enter the shared password
    (Supplier.authenticate, models.py). On success supplier_id goes into the
    session and the supplier lands on their own page. Like the other logins, it
    first logs out whoever was logged in.
    """
    request.session.pop("current_user", None)
    request.session.pop("customer_id", None)
    request.session.pop("supplier_id", None)

    error = None
    if request.method == "POST":
        supplier = Supplier.authenticate(
            request.POST.get("supplier_id", ""), request.POST.get("password", "")
        )
        if supplier is not None:
            request.session["supplier_id"] = supplier.supplier_id
            return redirect("djtraders:supplier_detail", supplier_id=supplier.supplier_id)
        error = "Incorrect supplier/password combination."

    suppliers = Supplier.objects.order_by("company_name")
    return render(request, "djtraders/suppliers/supplier_login.html", {"suppliers": suppliers, "error": error})


def supplier_logout_view(request):
    """Clears "supplier_id" from the session and returns to the home page."""
    request.session.pop("supplier_id", None)
    return redirect("djtraders:home")


def supplier_detail(request, supplier_id):
    """
    The supplier page shell: a header and a tab control (Info, Order History,
    Product Revenue), each tab a partial loaded by AJAX like the customer page.
    A visitor goes to the supplier login; a supplier asking for another
    supplier's page is sent back to their own.
    """
    logged_in_supplier_id = request.session.get("supplier_id")
    if logged_in_supplier_id and logged_in_supplier_id != supplier_id:
        return redirect("djtraders:supplier_detail", supplier_id=logged_in_supplier_id)
    if supplier_access_denied(request, supplier_id):
        return redirect("djtraders:supplier_login")
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/supplier_detail.html", {"supplier": supplier})


def supplier_info(request, supplier_id):
    """Info tab: contact details and headline numbers."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/_supplier_info.html", {
        "supplier": supplier,
        "summary": supplier.summary(),
    })


def supplier_orders(request, supplier_id):
    """Order History tab: placed orders that include this supplier's products."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/_supplier_orders.html", {
        "supplier": supplier,
        "orders": supplier.order_history(),
    })


def supplier_products(request, supplier_id):
    """Product Revenue tab: a table of units and revenue per product."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/_supplier_products.html", {
        "supplier": supplier,
        "rows": supplier.product_revenue(),
    })


def supplier_dashboard(request, supplier_id):
    """
    Dashboard tab: four summary tiles, revenue by year and by month (with a year
    dropdown), the category and top-product charts (each with controls), top
    customers, the comparison with all suppliers and the two questions of the data
    (share change by product, monthly pattern). Everything covers this supplier's own
    products only. The comparison reaches the page as plain numbers: no other
    supplier's name or figures (Supplier.comparison).
    """
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    years = supplier.order_years()
    share_years = supplier.default_share_years()
    return render(request, "djtraders/suppliers/_supplier_dashboard.html", {
        "supplier": supplier,
        "stats": supplier.dashboard_stats(),
        "annual_plot": supplier.annual_orders_plot(),
        "order_years": years,
        "category_revenue_plot": supplier.category_revenue_plot(top=10),
        "category_share_plot": supplier.unit_share_plot(top=10),
        "product_plot": supplier.top_products_plot("revenue", 10),
        "top_customers": supplier.top_customers(10),
        "comparison": supplier.comparison(),
        "compare_measures": Supplier.COMPARE_MEASURES,
        "comparison_plot": supplier.comparison_plot("revenue"),
        "share_years": sorted(years),
        "share_start": share_years[0] if share_years else None,
        "share_end": share_years[1] if share_years else None,
        "share_plot": supplier.share_change_plot(*share_years) if share_years else None,
        "pattern_plot": supplier.pattern_plot("revenue", "amount"),
    })


def supplier_monthly_chart(request, supplier_id):
    """
    The dashboard's year dropdown: Supplier.orders_placed_plot for ?year=, as just the
    chart HTML that fills #dashboard-monthly. The year comes from the browser, so it
    must be one of this supplier's order years (400 otherwise).
    """
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    try:
        year = int(request.GET.get("year", ""))
    except ValueError:
        return HttpResponse("Choose a valid year.", status=400)
    if year not in supplier.order_years():
        return HttpResponse("Choose a valid year.", status=400)
    return HttpResponse(supplier.orders_placed_plot(year) or "<p>No orders on record.</p>")


def supplier_category_chart(request, supplier_id):
    """
    The category charts for ?year= (all or one of this supplier's order years), ?top=
    (5, 10 or all) and ?kind= (pie or bar), as the fragment that fills
    #dashboard-category. Values are checked against fixed lists (400).
    """
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    year, year_ok = read_year(request, supplier.order_years())
    top, top_ok = read_top(request)
    kind, kind_ok = read_choice(request, "kind", ("pie", "bar"), "pie")
    if not (year_ok and top_ok and kind_ok):
        return HttpResponse("Choose a valid year, top and chart.", status=400)
    return render(request, "djtraders/suppliers/_supplier_category_charts.html", {
        "revenue_plot": supplier.category_revenue_plot(top, year),
        "share_plot": supplier.unit_share_plot(top, year, kind),
    })


def supplier_products_chart(request, supplier_id):
    """The top-products chart for ?top= (5, 10 or all) and ?measure= (revenue or units), as just the chart HTML (400 for any other value)."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    top, top_ok = read_top(request)
    measure, measure_ok = read_choice(request, "measure", ("revenue", "units"), "revenue")
    if not (top_ok and measure_ok):
        return HttpResponse("Choose a valid top and measure.", status=400)
    return HttpResponse(supplier.top_products_plot(measure, top) or "<p>No orders on record.</p>")


def supplier_comparison_chart(request, supplier_id):
    """The comparison chart for ?measure= (one of Supplier.COMPARE_MEASURES), as just the chart HTML. Only this supplier, the average and the nameless best are drawn."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    measure, ok = read_choice(request, "measure", Supplier.COMPARE_MEASURES, "revenue")
    if not ok:
        return HttpResponse("Choose a valid measure.", status=400)
    return HttpResponse(supplier.comparison_plot(measure) or "<p>No orders on record.</p>")


def supplier_share_chart(request, supplier_id):
    """
    The share-change chart for ?start= and ?end= (two of this supplier's order years),
    as just the chart HTML. Both years are checked (400); a start that is not earlier
    than the end gets a short message instead of a chart.
    """
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    years = supplier.order_years()
    try:
        start, end = int(request.GET.get("start", "")), int(request.GET.get("end", ""))
    except ValueError:
        return HttpResponse("Choose a valid pair of years.", status=400)
    if start not in years or end not in years:
        return HttpResponse("Choose a valid pair of years.", status=400)
    if start >= end:
        return HttpResponse("<p>Choose a From year that is earlier than the To year.</p>")
    return HttpResponse(supplier.share_change_plot(start, end) or "<p>No orders on record.</p>")


def supplier_pattern_chart(request, supplier_id):
    """The monthly-pattern heatmap for ?measure= (revenue, units or orders) and ?view= (amount or share), as just the chart HTML (400 for any other value)."""
    if supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    measure, measure_ok = read_choice(request, "measure", ("revenue", "units", "orders"), "revenue")
    view, view_ok = read_choice(request, "view", ("amount", "share"), "amount")
    if not (measure_ok and view_ok):
        return HttpResponse("Choose a valid measure and view.", status=400)
    return HttpResponse(supplier.pattern_plot(measure, view) or "<p>No orders on record.</p>")
