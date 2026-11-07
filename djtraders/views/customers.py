"""
Customer pages: the list, the detail page and its three tabs, edit / create /
deactivate, and the customer login.

A logged-in customer may only see and edit their own record (and build their own
cart); an employee may act on any customer's (see access.py).
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from ..forms import CustomerEditForm
from ..models import Customer
from .access import customer_access_denied, customer_tab_denied, own_customer_redirect
from .chart_params import read_choice, read_flag, read_top, read_year


def customer_list(request):
    """
    The customer list, searchable by company name, contact name, contact title,
    city and country. The five search values come from GET parameters ("" when
    not submitted) and Customer.search (models.py) turns them into the filter.
    Choosing a country narrows the city dropdown to that country's cities.

    A logged-in customer is sent straight to their own page instead
    (own_customer_redirect); employees and visitors see the full list.
    """
    redirect_response = own_customer_redirect(request, customer_id=None)
    if redirect_response:
        return redirect_response

    search_company_name = request.GET.get("company_name", "")
    search_contact_name = request.GET.get("contact_name", "")
    search_contact_title = request.GET.get("contact_title", "")
    search_city = request.GET.get("city", "")
    search_country = request.GET.get("country", "")

    # The dropdowns list the distinct, non-blank values on record.
    # Cities are narrowed to the selected country, if there is one.
    cities_queryset = Customer.objects.exclude(city__isnull=True).exclude(city__exact="")
    if search_country:
        cities_queryset = cities_queryset.filter(country=search_country)
    cities = cities_queryset.order_by("city").values_list("city", flat=True).distinct()

    countries = (
        Customer.objects.exclude(country__isnull=True)
        .exclude(country__exact="")
        .order_by("country")
        .values_list("country", flat=True)
        .distinct()
    )

    contact_titles = (
        Customer.objects.exclude(contact_title__isnull=True)
        .exclude(contact_title__exact="")
        .order_by("contact_title")
        .values_list("contact_title", flat=True)
        .distinct()
    )

    # A city left over from a different country would match nothing, so drop it.
    if search_city and search_city not in cities:
        search_city = ""

    customers = Customer.search(
        company_name=search_company_name,
        contact_name=search_contact_name,
        contact_title=search_contact_title,
        city=search_city,
        country=search_country,
    )

    context = {
        "customers": customers,
        "cities": cities,
        "countries": countries,
        "contact_titles": contact_titles,
        "search_company_name": search_company_name,
        "search_contact_name": search_contact_name,
        "search_contact_title": search_contact_title,
        "search_city": search_city,
        "search_country": search_country,
    }
    return render(request, "djtraders/customers/customer_list.html", context)


def customer_detail(request, customer_id):
    """
    A customer's page shell: the header and a Dashboard / Customer Info / Order
    History tab control. customer_id comes from the URL (see urls.py). A
    logged-in customer is redirected to their own page if the URL asks for
    another; employees and visitors may view any customer.
    """
    redirect_response = own_customer_redirect(request, customer_id)
    if redirect_response:
        return redirect_response

    customer = get_object_or_404(Customer, pk=customer_id)

    # Only the shell is built here; each tab's content comes from one of the
    # tab views below, loaded by AJAX once the page is open.
    return render(request, "djtraders/customers/customer_detail.html", {"customer": customer})


def customer_edit(request, customer_id):
    """
    Edits a customer with CustomerEditForm (forms.py); customer_edit.html draws
    it with django-crispy-forms. Open to an employee, or to that customer's own
    login (customer_access_denied).
    """
    customer = get_object_or_404(Customer, pk=customer_id)

    if customer_access_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    if request.method == "POST":
        form = CustomerEditForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            return redirect("djtraders:customer_detail", customer_id=customer.customer_id)
    else:
        form = CustomerEditForm(instance=customer)

    # ?confirm_delete=1 (the Delete icon on the list) shows an in-page "are you
    # sure?" prompt instead of the form; its Confirm button posts to customer_delete.
    confirm_delete = request.GET.get("confirm_delete") == "1"

    context = {"customer": customer, "form": form, "confirm_delete": confirm_delete}
    return render(request, "djtraders/customers/customer_edit.html", context)


def customer_create(request):
    """
    Creates a customer on the same page and form as customer_edit, for a Customer
    that is not in the database yet. Employees only. GET shows a blank form
    (new_customer=True, so the page says "New Customer"). A valid POST asks
    Customer.generate_customer_id (models.py) for a new ID built from the company
    name, saves once, and returns to the list.
    """
    if not request.session.get("current_user"):
        return redirect("djtraders:customer_list")

    if request.method == "POST":
        form = CustomerEditForm(request.POST, instance=Customer())
        if form.is_valid():
            # The ID needs the validated company name, so it is made after validation.
            form.instance.customer_id = Customer.generate_customer_id(
                form.cleaned_data["company_name"]
            )
            form.save()
            return redirect("djtraders:customer_list")
    else:
        form = CustomerEditForm(instance=Customer())

    context = {"customer": form.instance, "form": form, "new_customer": True}
    return render(request, "djtraders/customers/customer_edit.html", context)


def customer_delete(request, customer_id):
    """
    Marks a customer inactive (inactive_date = today) instead of deleting the
    row, which keeps their order history. Employees only, and POST only because
    it changes data.
    """
    if not request.session.get("current_user"):
        return redirect("djtraders:customer_list")

    if request.method == "POST":
        customer = get_object_or_404(Customer, pk=customer_id)
        customer.inactive_date = timezone.now().date()
        customer.save()

    return redirect("djtraders:customer_list")


# region [CONCEPT] the customer page's tabs are partial pages
# customer_detail renders only the shell. Each tab's content comes from a view
# below, fetched by AJAX (LoadPageTab in DjangoTraders.js) and returned as an
# HTML fragment with no base.html around it. A logged-in customer only gets
# their own tabs (another customer's gets a 403); employees and visitors may
# view any customer's.
# endregion
def customer_dashboard(request, customer_id):
    """
    Dashboard tab: four summary tiles (Customer.dashboard_stats), revenue by year
    and by month (with its year dropdown), the category charts and top-product
    charts (each with its own controls), and the "Buy it again" card. Everything
    covers only this customer's placed orders. The category and product charts
    arrive drawn with their default controls; a control then reloads just its own
    charts (customer_category_chart, customer_products_chart). With no placed
    orders the tab shows a message instead.
    """
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)

    context = {
        "customer": customer,
        "stats": customer.dashboard_stats(),
        "annual_plot": customer.annual_orders_plot(),
        "order_years": customer.order_years(),
        "category_revenue_plot": customer.category_revenue_plot(top=10),
        "category_share_plot": customer.unit_share_plot(top=10),
        "product_revenue_plot": customer.top_products_plot("revenue", 10),
        "product_units_plot": customer.top_products_plot("units", 10),
        "reorder_due": customer.reorder_due()[:5],
    }
    return render(request, "djtraders/customers/_customer_dashboard.html", context)


def customer_monthly_chart(request, customer_id):
    """
    The dashboard's year dropdown: Customer.orders_placed_plot for ?year=, as
    just the chart HTML that fills #dashboard-monthly. The year comes from the
    browser, so it is checked: 400 unless it is one of this customer's order years.
    """
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    try:
        year = int(request.GET.get("year", ""))
    except ValueError:
        return HttpResponse("Choose a valid year.", status=400)
    if year not in customer.order_years():
        return HttpResponse("Choose a valid year.", status=400)
    plot = customer.orders_placed_plot(year)
    return HttpResponse(plot or "<p>No orders on record.</p>")


def customer_category_chart(request, customer_id):
    """
    The category charts for ?year= (all or one of this customer's order years),
    ?top= (5, 10 or all) and ?kind= (pie or bar, for the unit share chart), as the
    fragment that fills #dashboard-category. One control set drives both charts.
    Every value is checked against a fixed list (400); another customer's tab is a 403.
    """
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    year, year_ok = read_year(request, customer.order_years())
    top, top_ok = read_top(request)
    kind, kind_ok = read_choice(request, "kind", ("pie", "bar"), "pie")
    if not (year_ok and top_ok and kind_ok):
        return HttpResponse("Choose a valid year, top and chart.", status=400)
    return render(request, "djtraders/customers/_customer_category_charts.html", {
        "revenue_plot": customer.category_revenue_plot(top, year),
        "share_plot": customer.unit_share_plot(top, year, kind),
    })


def customer_products_chart(request, customer_id):
    """
    The top-product charts for ?top= (5, 10 or all) and ?hide_discontinued= (0 or 1),
    as the fragment that fills #dashboard-products: top products by revenue beside top
    products by units. Values are checked (400); another customer's tab is a 403.
    """
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    top, top_ok = read_top(request)
    hide, hide_ok = read_flag(request, "hide_discontinued")
    if not (top_ok and hide_ok):
        return HttpResponse("Choose a valid top and discontinued setting.", status=400)
    return render(request, "djtraders/customers/_customer_products_charts.html", {
        "revenue_plot": customer.top_products_plot("revenue", top, hide),
        "units_plot": customer.top_products_plot("units", top, hide),
    })


def customer_info(request, customer_id):
    """
    Customer Info tab: the contact details and the Order Summary card, with its
    Start New Order button for an employee or the customer's own login.
    """
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)

    # order_set is the reverse accessor for this customer's orders. An order with
    # no order_date is a cart that was never committed, so it is left out.
    orders = customer.order_set.filter(order_date__isnull=False)
    total_quantity = sum(
        line.quantity for order in orders for line in order.orderdetail_set.all()
    )
    total_revenue = sum(order.order_total for order in orders)

    context = {
        "customer": customer,
        "total_quantity": total_quantity,
        "total_revenue": total_revenue,
        "can_start_order": not customer_access_denied(request, customer.customer_id),
    }
    return render(request, "djtraders/customers/_customer_info.html", context)


def customer_orders(request, customer_id):
    """Order History tab: the customer's placed orders, newest first, in a DataTable."""
    if customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    orders = customer.order_set.filter(order_date__isnull=False).order_by("-order_date")
    return render(request, "djtraders/customers/_customer_orders.html", {
        "customer": customer,
        "orders": orders,
    })


def customer_login_view(request):
    """
    Customer login: pick a company from a dropdown (Customer.authenticate,
    models.py). On success customer_id goes into the session and the customer
    lands on their own page. Landing here first logs out whoever was logged in,
    so there is only ever one login at a time.
    """
    request.session.pop("current_user", None)
    request.session.pop("customer_id", None)
    request.session.pop("supplier_id", None)

    error = None
    if request.method == "POST":
        customer_id = request.POST.get("customer_id", "")
        password = request.POST.get("password", "")
        customer = Customer.authenticate(customer_id, password)
        if customer is not None:
            request.session["customer_id"] = customer.customer_id
            return redirect("djtraders:customer_detail", customer_id=customer.customer_id)
        error = "Incorrect customer/password combination."

    customers = Customer.objects.order_by("company_name")
    context = {"customers": customers, "error": error}
    return render(request, "djtraders/customers/customer_login.html", context)


def customer_logout_view(request):
    """Clears "customer_id" from the session and returns to the home page."""
    request.session.pop("customer_id", None)
    return redirect("djtraders:home")
