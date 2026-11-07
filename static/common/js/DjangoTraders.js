/**
 * Project-wide custom JavaScript. base.html loads it after jQuery,
 * DataTables and jQuery UI, so everything here can rely on all three.
 * It holds what more than one kind of page uses, plus the supplier page's
 * table; the other entities' functions live in customers.js, employees.js
 * and orders.js.
 *
 *   MakeListDataTable, MakeOrdersDataTable, MakeProductRevenueDataTable - DataTables
 *   ActivatePageTabs, LoadPageTab          - load each tab's content by AJAX
 *   ActivateChartControls                  - dropdowns, radios and checkboxes that reload one chart
 */

// #region DataTables

/**
 * Customer and product lists: 20 rows per page, search box top right,
 * page-size menu bottom left, and no sorting on the last (Actions)
 * column, which holds icons, not data.
 * @param {string} tableId - selector for the table, e.g. "#customer-table"
 */
function MakeListDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [[10, 20, 25, 50, -1], [10, 20, 25, 50, "All"]],
        columnDefs: [{ targets: -1, orderable: false }],
        layout: {
            topStart: "info",
            topEnd: "search",
            bottomStart: "pageLength",
            bottomEnd: "paging"
        }
    });
}

/**
 * Any table of orders (a customer's, a product's, a supplier's), newest
 * first. Column 1 is Order Date; DataTables' own default sorts column 0 ascending.
 * @param {string} tableId - selector for the table
 */
function MakeOrdersDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [[10, 20, 25, 50, -1], [10, 20, 25, 50, "All"]],
        order: [[1, "desc"]]
    });
}

/**
 * A supplier's product revenue, biggest earners first (column 4).
 * @param {string} tableId - selector for the table
 */
function MakeProductRevenueDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [[10, 20, 25, 50, -1], [10, 20, 25, 50, "All"]],
        order: [[4, "desc"]]
    });
}

// #endregion

// #region Page tabs

/**
 * Wires up a Bootstrap tab control. Each tab's content is a partial
 * template fetched from the tab button's data-url and put into its pane,
 * the first time that tab is shown (see LoadPageTab).
 * @param {string} tabsSelector - selector for the tab list, e.g. "#employee-tabs"
 */
function ActivatePageTabs(tabsSelector) {
    const $tabs = $(tabsSelector);

    // Bootstrap fires shown.bs.tab on the button that just became active.
    $tabs.on("shown.bs.tab", "button[data-bs-toggle='tab']", function () {
        LoadPageTab($(this));
    });

    // The first tab is already active, so no event fires for it; load it directly.
    LoadPageTab($tabs.find("button.active"));
}

/**
 * Loads one tab's content (once), then switches on whatever it contains:
 * a DataTable for each known table id, and each dashboard control.
 * jQuery's .html() also runs the <script> inside each Plotly chart, which draws it.
 * @param {jQuery} $tabButton - the tab button that was shown
 */
function LoadPageTab($tabButton) {
    const $pane = $($tabButton.data("bs-target"));

    if ($pane.data("loaded")) {
        return;
    }
    $pane.text("Loading…");
    $.get($tabButton.data("url"))
        .done(function (html) {
            $pane.html(html).data("loaded", true);

            if ($pane.find("#orders-table").length) {
                MakeOrdersDataTable("#orders-table");
            }
            if ($pane.find("#supplier-orders-table").length) {
                MakeOrdersDataTable("#supplier-orders-table");
            }
            if ($pane.find("#product-revenue-table").length) {
                MakeProductRevenueDataTable("#product-revenue-table");
            }
            if ($pane.find("#employees-table").length) {
                MakeEmployeesDataTable("#employees-table");
            }
            if ($pane.find("#leaderboard-table").length) {
                MakeLeaderboardDataTable("#leaderboard-table");
            }

            ActivateYearDropdown($pane);
            ActivateChartControls($pane);
            ActivateBreakdownControls($pane);
            ActivateCustomerControls($pane);
            ActivateTeamComparison($pane);
            ActivateRevenueOverTime($pane);
        })
        .fail(function () {
            $pane.text("Could not load this tab. Please try again.");
        });
}

// #endregion

// #region Chart controls

/**
 * Wires every control bar on a dashboard that reloads a chart. A control bar is any
 * element with class js-chart-controls, carrying data-url (the view that answers)
 * and data-target (the selector of the div the answer replaces). Each dropdown, radio
 * button or checkbox inside it names its query-string key with data-param. When one
 * changes, the bar sends ALL its current values to the view with $.get and swaps the
 * returned HTML into the target, so a new control needs no JavaScript of its own:
 * only the markup and a view. A checkbox is sent as 1 or 0. The server checks every
 * value, because the query string is typed by the browser.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateChartControls($pane) {
    $pane.find(".js-chart-controls").each(function () {
        const $bar = $(this);
        const $target = $($bar.data("target"));

        function currentValues() {
            const values = {};
            $bar.find("[data-param]").each(function () {
                const $control = $(this);
                const key = $control.data("param");
                if ($control.is(":radio")) {
                    if ($control.is(":checked")) { values[key] = $control.val(); }
                } else if ($control.is(":checkbox")) {
                    values[key] = $control.is(":checked") ? 1 : 0;
                } else {
                    values[key] = $control.val();
                }
            });
            return values;
        }

        $bar.on("change", "[data-param]", function () {
            $.get($bar.data("url"), currentValues())
                .done(function (html) { $target.html(html); })
                .fail(function () { $target.text("Could not load the chart."); });
        });
    });
}

// #endregion
