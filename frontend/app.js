const $ = id => document.getElementById(id);

let state = {
  rows: [],
  inventory: [],
  purchase_orders: [],
  draft: null,
  transfer: null,
  charts: {}
};

const titles = {
  overview: "Supply chain overview",
  inventory: "Inventory analytics",
  "purchase-orders": "Purchase order monitoring",
  actions: "AI recommendation desk",
  transfers: "Inventory transfer center",
  history: "Decision history"
};

const esc = v =>
  String(v ?? "—").replace(/[&<>"']/g, c => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[c]));

const num = v => {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 3300);
}

function showError(msg) {
  const e = $("error-banner");
  e.textContent = msg;
  e.classList.remove("hidden");
}

function clearError() {
  $("error-banner").classList.add("hidden");
}

async function api(url, options = {}) {
  let response;

  try {
    response = await fetch(url, {
      ...options,
      headers: {
        ...(options.headers || {}),
        ...(options.body
          ? { "Content-Type": "application/json" }
          : {})
      }
    });
  } catch (error) {
    throw new Error(
      `Cannot connect to the backend. Check that the server is running. ${error.message}`
    );
  }

  const raw = await response.text();
  let data = {};

  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      data = { detail: raw };
    }
  }

  if (!response.ok) {
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `Request failed with HTTP ${response.status}`
    );
  }

  return data;
}

/* ---------------- NAVIGATION ---------------- */

function showView(view) {
  document.querySelectorAll(".view").forEach(x =>
    x.classList.toggle("active", x.id === "view-" + view)
  );

  document.querySelectorAll(".nav").forEach(x =>
    x.classList.toggle("active", x.dataset.view === view)
  );

  $("page-title").textContent =
    titles[view] || "SpareSense AI";

  if (view === "history") {
    loadHistory();
  }
}

document.querySelectorAll(".nav").forEach(b =>
  b.addEventListener("click", () =>
    showView(b.dataset.view)
  )
);

document.querySelectorAll("[data-go]").forEach(b =>
  b.addEventListener("click", () =>
    showView(b.dataset.go)
  )
);

/* ---------------- INVENTORY RISK ---------------- */

function riskFor(r) {
  if (
    r.shortage_risk === true ||
    String(r.shortage_risk).toLowerCase() === "true"
  ) {
    return "Critical";
  }

  const days = num(r.days_of_stock);
  const lead = num(r.fastest_lead_days);

  if (
    days !== null &&
    lead !== null &&
    days < lead
  ) {
    return "At risk";
  }

  return "Healthy / monitor";
}

/* ---------------- CHARTS ---------------- */

function makeChart(id, type, data, opts = {}) {
  if (state.charts[id]) {
    state.charts[id].destroy();
  }

  const ctx = $(id);
  if (!ctx) return;

  state.charts[id] = new Chart(ctx, {
    type,
    data,
    options: {
      responsive: true,
      maintainAspectRatio: false,

      plugins: {
        legend: {
          labels: {
            color: "#90a9bb",
            boxWidth: 9,
            font: { size: 10 }
          }
        }
      },

      scales: type === "doughnut" ? {} : {
        x: {
          ticks: {
            color: "#7895a8",
            font: { size: 10 }
          },
          grid: { color: "#1a2d3b" }
        },
        y: {
          ticks: { color: "#7895a8" },
          grid: { color: "#1a2d3b" }
        }
      },

      ...opts
    }
  });
}

/* ---------------- DASHBOARD ---------------- */

async function loadDashboard() {
  clearError();

  try {
    const d = await api("/api/dashboard");

    state.rows = d.rows || [];
    state.inventory = d.inventory || [];
    state.purchase_orders = d.purchase_orders || [];

    $("metric-records").textContent =
      d.metrics.records ?? 0;

    $("metric-shortages").textContent =
      d.metrics.shortages ?? 0;

    $("metric-locations").textContent =
      d.metrics.locations ?? 0;

    $("metric-overdue").textContent =
      d.metrics.overdue ?? 0;

    $("last-updated").textContent =
      "Updated " + new Date().toLocaleTimeString();

    const skus = [
      ...new Set(state.rows.map(r => r.sku))
    ];

    const locs = [
      ...new Set(state.rows.map(r => r.location))
    ];

    const stockSets = locs.map((loc, i) => ({
      label: loc,

      data: skus.map(s => {
        const matchingRows = state.rows.filter(
          r => r.sku === s && r.location === loc
        );

        return matchingRows.reduce(
          (total, r) => total + (num(r.stock) || 0),
          0
        );
      }),

      backgroundColor: [
        "#36e0c1",
        "#5ba9ff",
        "#a18bff",
        "#ffc56b",
        "#ff8193"
      ][i % 5],

      borderRadius: 5
    }));

    makeChart(
      "stock-chart",
      "bar",
      {
        labels: skus,
        datasets: stockSets
      },
      {
        scales: {
          x: {
            ticks: {
              color: "#7895a8",
              font: { size: 10 }
            },
            grid: { display: false }
          },

          y: {
            ticks: { color: "#7895a8" },
            grid: { color: "#1a2d3b" }
          }
        }
      }
    );

    const risks = state.rows.map(riskFor);

    const labels = [
      "Critical",
      "At risk",
      "Healthy / monitor"
    ];

    const counts = labels.map(label =>
      risks.filter(risk => risk === label).length
    );

    makeChart(
      "risk-chart",
      "doughnut",
      {
        labels,

        datasets: [{
          data: counts,

          backgroundColor: [
            "#ff6d7d",
            "#ffc56b",
            "#36e0c1"
          ],

          borderColor: "#0d1b2a",
          borderWidth: 4,
          hoverOffset: 5
        }]
      },
      {
        cutout: "72%",
        plugins: {
          legend: { display: false }
        }
      }
    );

    $("risk-legend").innerHTML = labels.map(
      (label, i) =>
        `<span style="--dot:${[
          "#ff6d7d",
          "#ffc56b",
          "#36e0c1"
        ][i]}">${esc(label)} · ${counts[i]}</span>`
    ).join("");

    const priority = {
      Critical: 0,
      "At risk": 1,
      "Healthy / monitor": 2
    };

    const sorted = [...state.rows].sort(
      (a, b) => priority[riskFor(a)] - priority[riskFor(b)]
    );

    $("priority-list").innerHTML = sorted
      .slice(0, 5)
      .map(r => `
        <div class="priority-item">
          <div class="priority-mark">
            ${riskFor(r) === "Critical" ? "!" : "↗"}
          </div>

          <div class="priority-info">
            <b>${esc(r.sku)} · ${esc(r.location)}</b>
            <small>
              ${esc(r.stock)} units on hand ·
              ${esc(r.days_of_stock ?? "—")} days of stock
            </small>
          </div>

          <span class="risk-pill">
            ${esc(riskFor(r))}
          </span>
        </div>
      `)
      .join("") ||
      '<div class="empty">No analysis records available.</div>';

    renderInventory();
    renderPurchaseOrders();
    fillTransferForm();
    fillActionForm();

    const totals = {};

    state.inventory.forEach(r => {
      totals[r.location] =
        (totals[r.location] || 0) +
        (num(r.stock) || 0);
    });

    makeChart(
      "warehouse-chart",
      "bar",
      {
        labels: Object.keys(totals),

        datasets: [{
          label: "Reported units",
          data: Object.values(totals),
          backgroundColor: "#36e0c1",
          borderRadius: 5
        }]
      }
    );

  } catch (e) {
    showError(
      "Dashboard could not load: " +
      e.message +
      ". Check that analysis.py, actions.py and the data CSV files are in the project root."
    );
  }
}

/* ---------------- INVENTORY TABLE ---------------- */

function renderInventory() {
  const query =
    ($("inventory-search").value || "").toLowerCase();

  const rows = state.rows.filter(r =>
    `${r.sku} ${r.location}`
      .toLowerCase()
      .includes(query)
  );

  $("inventory-table").innerHTML = rows.map(r => {
    const risk = riskFor(r);

    const riskClass =
      risk === "Critical"
        ? "critical"
        : risk === "At risk"
          ? "watch"
          : "";

    return `
      <tr>
        <td><b>${esc(r.sku)}</b></td>
        <td>${esc(r.location)}</td>
        <td>${esc(r.stock)}</td>
        <td>${esc(r.daily_demand)}</td>
        <td>${esc(r.days_of_stock)}</td>
        <td>${esc(r.fastest_lead_days)}</td>
        <td>
          <span class="risk-chip ${riskClass}">
            ${esc(risk)}
          </span>
        </td>
      </tr>
    `;
  }).join("") ||
    '<tr><td colspan="7">No matching records</td></tr>';
}

$("inventory-search").addEventListener(
  "input",
  renderInventory
);

/* ---------------- PURCHASE ORDERS ---------------- */

function renderPurchaseOrders() {
  const pos = state.purchase_orders;

  const all = pos.length
    ? pos
    : state.rows
        .filter(r => r.open_po_qty !== undefined)
        .map(r => ({
          sku: r.sku,
          open_po_qty: r.open_po_qty,
          overdue_po_count: r.overdue_po_count
        }));

  const overdueCount = state.rows.reduce(
    (total, r) =>
      total + (num(r.overdue_po_count) || 0),
    0
  );

  $("po-alerts").innerHTML = [
    ["OPEN ORDER ROWS", pos.length],
    ["OVERDUE RECORDS", overdueCount],
    [
      "SKUs IN ANALYSIS",
      new Set(state.rows.map(r => r.sku)).size
    ]
  ].map(([label, value]) => `
    <article class="metric">
      <div class="metric-top">${label}</div>
      <strong>${value}</strong>
      <small>From local analysis data</small>
    </article>
  `).join("");

  const cols = all.length
    ? Object.keys(all[0])
    : [];

  $("po-head").innerHTML =
    "<tr>" +
    cols.map(c =>
      `<th>${esc(c.replaceAll("_", " ").toUpperCase())}</th>`
    ).join("") +
    "</tr>";

  $("po-table").innerHTML = all.map(r =>
    "<tr>" +
    cols.map(c => `<td>${esc(r[c])}</td>`).join("") +
    "</tr>"
  ).join("") ||
    `<tr><td colspan="${Math.max(cols.length, 1)}">No purchase-order rows found. Check your data/purchase_orders.csv filename and schema.</td></tr>`;
}

/* ---------------- AI RECOMMENDATIONS ---------------- */

function fillActionForm() {
  const criticalRows = state.rows.filter(
    r =>
      riskFor(r) === "Critical" ||
      riskFor(r) === "At risk"
  );

  $("action-target").innerHTML = criticalRows.map(
    (r, i) =>
      `<option value="${i}">${esc(r.sku)} — ${esc(r.location)} (${esc(riskFor(r))})</option>`
  ).join("");

  $("action-target").dataset.rows =
    JSON.stringify(criticalRows);

  if (!criticalRows.length) {
    $("action-target").innerHTML =
      '<option value="">No shortage-risk records</option>';
  }
}

$("generate-action").addEventListener(
  "click",
  async () => {
    try {
      const rows = JSON.parse(
        $("action-target").dataset.rows || "[]"
      );

      const row = rows[
        Number($("action-target").value)
      ];

      if (!row) {
        return toast("No shortage record selected.");
      }

      const result = await api(
        "/api/actions/draft",
        {
          method: "POST",

          body: JSON.stringify({
            sku: String(row.sku),
            location: String(row.location)
          })
        }
      );

      state.draft = result.draft;

      renderActionDraft();

      toast("Action draft created for review.");

    } catch (e) {
      toast(e.message);
    }
  }
);

function renderActionDraft() {
  const d = state.draft;
  if (!d) return;

  $("action-status").textContent = d.status;

  $("action-draft").innerHTML = `
    <div class="draft-kpis">
      <div class="draft-kpi">
        <small>SKU / LOCATION</small>
        <b>${esc(d.sku)} · ${esc(d.location)}</b>
      </div>

      <div class="draft-kpi">
        <small>RECOMMENDED ACTION</small>
        <b>${esc(
          d.action ||
          d.action_type ||
          d.recommendation ||
          "Review"
        )}</b>
      </div>
    </div>

    <pre>${esc(JSON.stringify(d, null, 2))}</pre>
  `;

  $("action-decision-buttons").classList.toggle(
    "hidden",
    d.status !== "PENDING_APPROVAL"
  );
}

document.querySelectorAll("[data-action-decision]")
  .forEach(button => {
    button.addEventListener("click", async () => {
      if (
        !state.draft ||
        state.draft.status !== "PENDING_APPROVAL"
      ) {
        return;
      }

      const decision = button.dataset.actionDecision;

      if (!confirm(
        `${decision} this action draft? This only records a decision. It will not create a PO or move stock.`
      )) {
        return;
      }

      try {
        const result = await api(
          "/api/decisions",
          {
            method: "POST",

            body: JSON.stringify({
              draft_id: state.draft.draft_id,
              decision
            })
          }
        );

        state.draft.status = decision;

        if (result.decision) {
          state.draft.decided_at =
            result.decision.decided_at;
        }

        renderActionDraft();

        $("action-decision-note").textContent =
          result.note || "Decision recorded.";

        $("action-decision-note").classList.remove(
          "hidden"
        );

        toast(
          "Decision saved. No real-world action was executed."
        );

      } catch (e) {
        toast(e.message);
      }
    });
  });

/* ---------------- TRANSFER CENTER ---------------- */

function clearTransferDraft() {
  // Clear the current review only.
  // Saved history remains intact.
  state.transfer = null;

  $("transfer-status").textContent = "NO DRAFT";

  $("transfer-draft").innerHTML =
    '<div class="empty">Your proposed transfer will appear here.</div>';

  $("transfer-decision-buttons").classList.add(
    "hidden"
  );

  $("save-transfer-history").classList.add(
    "hidden"
  );

  $("transfer-note").textContent = "";

  $("transfer-note").classList.add(
    "hidden"
  );
}

function fillTransferForm() {
  const skus = [
    ...new Set(
      state.inventory.map(r => String(r.sku))
    )
  ];

  $("transfer-sku").innerHTML = skus.map(s =>
    `<option value="${esc(s)}">${esc(s)}</option>`
  ).join("");

  updateTransferLocations();
}

function updateTransferLocations() {
  const sku = $("transfer-sku").value;

  const locations = [
    ...new Set(
      state.inventory
        .filter(r => String(r.sku) === sku)
        .map(r => String(r.location))
    )
  ];

  const previousSource =
    $("transfer-source").value;

  $("transfer-source").innerHTML =
    locations.map(location =>
      `<option value="${esc(location)}">${esc(location)}</option>`
    ).join("");

  if (locations.includes(previousSource)) {
    $("transfer-source").value = previousSource;
  }

  updateTransferDestinations();
}

function updateTransferDestinations() {
  const sku = $("transfer-sku").value;
  const source = $("transfer-source").value;

  const locations = [
    ...new Set(
      state.inventory
        .filter(r => String(r.sku) === sku)
        .map(r => String(r.location))
    )
  ].filter(location => location !== source);

  const previousDestination =
    $("transfer-destination").value;

  $("transfer-destination").innerHTML =
    locations.map(location =>
      `<option value="${esc(location)}">${esc(location)}</option>`
    ).join("");

  if (locations.includes(previousDestination)) {
    $("transfer-destination").value =
      previousDestination;
  }

  updateTransferPreview();
}

function getStock(sku, location) {
  const row = state.inventory.find(
    r =>
      String(r.sku) === sku &&
      String(r.location) === location
  );

  return row ? num(row.stock) : null;
}

function updateTransferPreview() {
  const sku = $("transfer-sku").value;
  const source = $("transfer-source").value;
  const destination =
    $("transfer-destination").value;

  const sourceStock = getStock(sku, source);
  const destinationStock =
    getStock(sku, destination);

  const buffer = Math.max(
    0,
    Number($("transfer-buffer").value) || 0
  );

  const quantity = Math.max(
    0,
    Number($("transfer-qty").value) || 0
  );

  const sourceAfter =
    sourceStock === null
      ? null
      : sourceStock - quantity;

  const destinationAfter =
    destinationStock === null
      ? null
      : destinationStock + quantity;

  const bufferOk =
    sourceAfter !== null &&
    sourceAfter >= buffer;

  $("transfer-stock-preview").innerHTML = `
    <b>Current stock</b><br>

    ${esc(source || "Source")}:
    ${sourceStock ?? "—"} units ·

    ${esc(destination || "Destination")}:
    ${destinationStock ?? "—"} units

    <br>

    <b>After proposed transfer</b><br>

    Source: ${sourceAfter ?? "—"} ·
    Destination: ${destinationAfter ?? "—"}

    <br>

    <span style="color:${
      bufferOk ? "#36e0c1" : "#ff8193"
    }">

      Source safety buffer: ${buffer} units ·

      ${
        bufferOk
          ? "Within buffer"
          : "Would breach buffer"
      }

    </span>
  `;
}

// Any change invalidates the old draft.
// The user must generate a new draft before deciding.

$("transfer-sku").addEventListener(
  "change",
  () => {
    clearTransferDraft();

    $("transfer-qty").value = "1";

    updateTransferLocations();
  }
);

$("transfer-source").addEventListener(
  "change",
  () => {
    clearTransferDraft();
    updateTransferDestinations();
  }
);

$("transfer-destination").addEventListener(
  "change",
  () => {
    clearTransferDraft();
    updateTransferPreview();
  }
);

$("transfer-buffer").addEventListener(
  "input",
  () => {
    clearTransferDraft();
    updateTransferPreview();
  }
);

$("transfer-qty").addEventListener(
  "input",
  () => {
    clearTransferDraft();
    updateTransferPreview();
  }
);

$("generate-transfer").addEventListener(
  "click",
  async () => {
    try {
      const request = {
        sku: $("transfer-sku").value,

        from_location:
          $("transfer-source").value,

        to_location:
          $("transfer-destination").value,

        quantity:
          Number($("transfer-qty").value),

        donor_safety_buffer:
          Number($("transfer-buffer").value)
      };

      if (
        !request.sku ||
        !request.from_location ||
        !request.to_location
      ) {
        return toast(
          "Select a SKU and two locations."
        );
      }

      if (
        request.from_location ===
        request.to_location
      ) {
        return toast(
          "Source and destination must be different."
        );
      }

      if (
        !Number.isInteger(request.quantity) ||
        request.quantity <= 0 ||
        !Number.isInteger(
          request.donor_safety_buffer
        ) ||
        request.donor_safety_buffer < 0
      ) {
        return toast(
          "Quantity must be a positive whole number and safety buffer must be a non-negative whole number."
        );
      }

      // Clear the old review before requesting a new draft.
      clearTransferDraft();

      const result = await api(
        "/api/transfers/draft",
        {
          method: "POST",
          body: JSON.stringify(request)
        }
      );

      if (!result.draft) {
        throw new Error(
          "The backend did not return a transfer draft."
        );
      }

      state.transfer = result.draft;

      renderTransfer();

      toast(
        "Transfer draft created. Review before deciding."
      );

    } catch (e) {
      clearTransferDraft();
      toast(e.message);
    }
  }
);

function renderTransfer() {
  const d = state.transfer;

  if (!d) {
    clearTransferDraft();
    return;
  }

  $("transfer-status").textContent = d.status;

  $("transfer-draft").innerHTML = `
    <div class="draft-kpis">

      <div class="draft-kpi">
        <small>SKU</small>
        <b>${esc(d.sku)}</b>
      </div>

      <div class="draft-kpi">
        <small>TRANSFER</small>
        <b>
          ${esc(d.from_location)}
          →
          ${esc(d.to_location)}
        </b>
      </div>

      <div class="draft-kpi">
        <small>QUANTITY</small>
        <b>${esc(d.quantity)} units</b>
      </div>

      <div class="draft-kpi">
        <small>SOURCE AFTER</small>
        <b>${esc(d.estimated_source_after)} units</b>
      </div>

      <div class="draft-kpi">
        <small>DESTINATION AFTER</small>
        <b>${esc(d.estimated_destination_after)} units</b>
      </div>

    </div>

    <pre>${esc(JSON.stringify(d, null, 2))}</pre>
  `;

  $("transfer-decision-buttons").classList.toggle(
    "hidden",
    d.status !== "PENDING_APPROVAL"
  );

  $("save-transfer-history").classList.toggle(
    "hidden",
    !["APPROVED", "REJECTED"].includes(d.status)
  );
}

/* ---------------- TRANSFER DECISIONS ---------------- */

document.querySelectorAll("[data-transfer-decision]")
  .forEach(button => {
    button.addEventListener("click", async () => {
      if (
        !state.transfer ||
        state.transfer.status !== "PENDING_APPROVAL"
      ) {
        return;
      }

      const decision =
        button.dataset.transferDecision;

      if (!confirm(
        `${decision} this transfer proposal? This records your decision only. Inventory will not be modified.`
      )) {
        return;
      }

      try {
        const result = await api(
          "/api/transfers/decision",
          {
            method: "POST",

            body: JSON.stringify({
              draft_id: state.transfer.draft_id,
              decision
            })
          }
        );

        if (result.draft) {
          state.transfer = result.draft;
        } else {
          state.transfer.status = decision;
          state.transfer.decided_at =
            new Date().toISOString();
        }

        renderTransfer();

        $("transfer-note").textContent =
          decision === "APPROVED"
            ? "Transfer proposal approved. No inventory was changed and no physical transfer was executed."
            : "Transfer proposal rejected. No stock was moved.";

        $("transfer-note").classList.remove(
          "hidden"
        );

        toast(
          "Decision recorded. Save to history to persist."
        );

      } catch (e) {
        toast(e.message);
      }
    });
  });

/* ---------------- SAVE TRANSFER HISTORY ---------------- */

$("save-transfer-history").addEventListener(
  "click",
  async () => {
    if (
      !state.transfer ||
      !["APPROVED", "REJECTED"].includes(
        state.transfer.status
      )
    ) {
      return toast(
        "Approve or reject a transfer before saving history."
      );
    }

    try {
      const result = await api(
        "/api/transfers/history",
        {
          method: "POST",
          body: JSON.stringify(state.transfer)
        }
      );

      $("transfer-note").textContent =
        result.message;

      $("transfer-note").classList.remove(
        "hidden"
      );

      toast(result.message);

      loadHistory();

    } catch (e) {
      toast(e.message);
    }
  }
);

/* ---------------- DECISION HISTORY ---------------- */

async function loadHistory() {
  try {
    const rows = await api(
      "/api/transfers/history"
    );

    const cols = rows.length
      ? Object.keys(rows[0])
      : [];

    $("history-head").innerHTML =
      "<tr>" +
      cols.map(c =>
        `<th>${esc(
          c.replaceAll("_", " ").toUpperCase()
        )}</th>`
      ).join("") +
      "</tr>";

    $("history-table").innerHTML =
      rows.map(r =>
        "<tr>" +
        cols.map(c =>
          `<td>${esc(r[c])}</td>`
        ).join("") +
        "</tr>"
      ).join("") ||
      '<tr><td>No saved transfer decisions yet.</td></tr>';

  } catch (e) {
    toast(e.message);
  }
}

$("refresh-history").addEventListener(
  "click",
  loadHistory
);

$("refresh-btn").addEventListener(
  "click",
  loadDashboard
);

/* ---------------- START APPLICATION ---------------- */

loadDashboard();