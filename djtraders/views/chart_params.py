"""
Reading and checking the values a dashboard control sends. A chart's control puts
its choice in the query string (?top=5&year=2025), which anyone can edit by hand,
so every view checks each value against a fixed list before it draws anything: a
value that is not on the list is a 400. Each reader returns (value, ok).
"""

TOP_CHOICES = ("5", "10", "all")


def read_top(request, allowed=TOP_CHOICES, default="10"):
    """?top= as a number, or None for "all". ok is False unless it is one of allowed."""
    top = request.GET.get("top", default)
    if top not in allowed:
        return None, False
    return (None if top == "all" else int(top)), True


def read_year(request, years):
    """?year= as a number, or None for "all". ok is False unless it is "all" or one of years."""
    year = request.GET.get("year", "all")
    if year == "all":
        return None, True
    if year.isdigit() and int(year) in years:
        return int(year), True
    return None, False


def read_choice(request, name, allowed, default):
    """?name= as a string. ok is False unless it is one of allowed."""
    value = request.GET.get(name, default)
    return value, value in allowed


def read_flag(request, name):
    """A checkbox, sent as 0 or 1. ok is False for anything else."""
    value = request.GET.get(name, "0")
    return value == "1", value in ("0", "1")
