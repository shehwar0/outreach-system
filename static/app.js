/* ─── Helpers ─────────────────────────────────────────────────── */

function safeText(value) {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function statusBadge(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}

/* ─── Tab Navigation ──────────────────────────────────────────── */

function initTabs() {
  const navButtons = document.querySelectorAll(".nav-item[data-tab]");
  const panels = document.querySelectorAll(".tab-panel");

  navButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;

      navButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      panels.forEach((p) => p.classList.remove("active"));
      const target = document.getElementById("tab" + capitalize(tab));
      if (target) target.classList.add("active");

      if (tab === "campaigns") loadCampaigns();
      if (tab === "leads") loadLeads();
    });
  });
}

function capitalize(str) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

/* ─── Campaign Status Polling ────────────────────────────────── */

function updateStatusCards(status) {
  const el = (id) => document.getElementById(id);

  el("metricTotal").textContent = safeText(status.total_leads || 0);
  el("metricAttempted").textContent = safeText(status.attempted || 0);
  el("metricSent").textContent = safeText(status.sent || 0);
  el("metricFailed").textContent = safeText(status.failed || 0);
  el("metricSkipped").textContent = safeText(status.skipped_duplicates || 0);
  el("metricRunning").textContent = status.running ? "Yes" : "No";

  el("statusMessage").textContent = safeText(status.message);
  el("statusRecipient").textContent = safeText(status.current_recipient);

  const total = Number(status.total_leads || 0);
  const done = Number(status.attempted || 0) + Number(status.skipped_duplicates || 0);
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;

  el("progressText").textContent = percent + "%";
  el("progressFill").style.width = percent + "%";
}

function renderLogs(rows) {
  const body = document.getElementById("logsBody");
  if (!body) return;

  body.innerHTML = "";
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${safeText(row.timestamp)}</td>
      <td>${safeText(row.recipient_email)}</td>
      <td>${safeText(row.sender_email)}</td>
      <td>${statusBadge(row.status || "unknown")}</td>
      <td>${safeText(row.error)}</td>
    `;
    body.appendChild(tr);
  });
}

async function pollStatus() {
  try {
    const res = await fetch("/status", { cache: "no-store" });
    if (!res.ok) return;
    const status = await res.json();
    updateStatusCards(status);
  } catch (e) {}
}

async function pollLogs() {
  try {
    const res = await fetch("/logs/recent?limit=25", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    renderLogs(Array.isArray(data.rows) ? data.rows : []);
  } catch (e) {}
}

/* ─── Leads ──────────────────────────────────────────────────── */

async function loadLeads() {
  const segment = document.getElementById("filterSegment").value;
  const stage = document.getElementById("filterStage").value;

  let url = "/api/leads?";
  if (segment) url += `segment=${segment}&`;
  if (stage) url += `funnel_stage=${stage}&`;

  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    renderLeads(data.leads || []);
  } catch (e) {}
}

function renderLeads(leads) {
  const body = document.getElementById("leadsBody");
  if (!body) return;

  body.innerHTML = "";
  leads.forEach((l) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${safeText(l.name)}</td>
      <td>${safeText(l.email)}</td>
      <td>${safeText(l.business)}</td>
      <td>${safeText(l.city)}</td>
      <td><strong>${l.lead_score || 0}</strong></td>
      <td><span class="badge badge-${l.segment}">${l.segment}</span></td>
      <td><span class="badge badge-stage-${l.funnel_stage}">${l.funnel_stage}</span></td>
      <td>${safeText(l.niche)}</td>
    `;
    body.appendChild(tr);
  });
}

/* ─── Replies ─────────────────────────────────────────────────── */

function initReplyHandlers() {
  // Log new reply
  const btnLog = document.getElementById("btnLogReply");
  if (btnLog) {
    btnLog.addEventListener("click", async () => {
      const email = document.getElementById("replyEmail").value.trim();
      const text = document.getElementById("replyText").value.trim();
      const type = document.getElementById("replyType").value;

      if (!email) { alert("Enter lead email"); return; }

      try {
        const res = await fetch("/api/replies", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, reply_text: text, reply_type: type }),
        });
        const data = await res.json();
        if (data.ok) {
          document.getElementById("replyEmail").value = "";
          document.getElementById("replyText").value = "";
          location.reload();
        } else {
          alert(data.error || "Error logging reply");
        }
      } catch (e) { alert("Network error"); }
    });
  }

  // Classify replies
  document.addEventListener("click", async (e) => {
    if (!e.target.classList.contains("classify-btn")) return;
    const tr = e.target.closest("tr");
    if (!tr) return;

    const replyId = tr.dataset.replyId;
    const select = tr.querySelector(".classify-select");
    const replyType = select ? select.value : "";

    if (!replyType) { alert("Select a classification"); return; }

    try {
      const res = await fetch(`/api/replies/${replyId}/classify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reply_type: replyType }),
      });
      const data = await res.json();
      if (data.ok) {
        tr.style.opacity = "0.3";
        setTimeout(() => tr.remove(), 500);
      }
    } catch (e) { alert("Network error"); }
  });
}

/* ─── Campaigns ──────────────────────────────────────────────── */

async function loadCampaigns() {
  try {
    const res = await fetch("/api/campaigns", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    renderCampaigns(data.campaigns || []);
  } catch (e) {}
}

function renderCampaigns(campaigns) {
  const body = document.getElementById("campaignsBody");
  if (!body) return;

  body.innerHTML = "";
  campaigns.forEach((c) => {
    const tr = document.createElement("tr");
    const statusClass = c.status === "completed" ? "sent" : c.status === "running" ? "badge-stage-contacted" : "failed";
    tr.innerHTML = `
      <td>${c.id}</td>
      <td>${safeText(c.name)}</td>
      <td>${safeText(c.campaign_type)}</td>
      <td><span class="badge badge-${statusClass}">${c.status}</span></td>
      <td>${safeText(c.created_at)}</td>
      <td>${safeText(c.finished_at)}</td>
    `;
    body.appendChild(tr);
  });
}

/* ─── Filter button ──────────────────────────────────────────── */

function initFilters() {
  const btn = document.getElementById("btnFilterLeads");
  if (btn) btn.addEventListener("click", loadLeads);
}

/* ─── Toast auto-hide ─────────────────────────────────────────── */

function autoHideToasts() {
  document.querySelectorAll(".toast").forEach((toast) => {
    setTimeout(() => { toast.style.opacity = "0"; setTimeout(() => toast.remove(), 300); }, 4000);
  });
}

/* ─── Polling Tick ────────────────────────────────────────────── */

async function tick() {
  await Promise.all([pollStatus(), pollLogs()]);
}

/* ─── Init ────────────────────────────────────────────────────── */

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initReplyHandlers();
  initFilters();
  autoHideToasts();
  tick();
  setInterval(tick, 3000);
});
