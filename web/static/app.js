(() => {
  const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  const numberFormatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });

  const labels = {
    orderType: { normal: "普通", urgent: "加急", vip: "VIP" },
    certification: { ccc: "CCC", cvc: "CVC", international: "国际" },
    status: {
      pending: "待排程",
      created: "已创建",
      scheduled: "已排程",
      running: "运行中",
      paused: "已暂停",
      completed: "已完成",
      cancelled: "已取消",
      blocked: "阻塞",
      triggered: "已触发",
      read: "已读",
      done: "已处理",
      processing: "处理中",
      failed: "失败",
      ignored: "忽略",
      imported: "已导入",
    },
    stepKind: {
      preprocessing: "前处理",
      setup: "准备",
      detection: "检测",
      transfer: "转运",
    },
    notificationType: {
      equipment_idle: "设备空闲",
      detection_completed: "检测完成",
      sample_preprocessing_todo: "样品前处理",
      sample_transfer_required: "样品转运",
      sla_risk: "SLA风险",
      maintenance_warning: "维护临近",
      consumable_shortage: "耗材不足",
      personnel_blocked: "人员阻塞",
      review_pending: "复核待办",
      order_blocked: "订单阻塞",
      auto_reschedule_completed: "自动重排完成",
      retest_required: "复检要求",
    },
    sla: {
      delayed: "延期",
      on_time: "准时",
      not_applicable: "无承诺时间",
    },
  };

  let currentScheduleSteps = new Map();
  let currentReplayRunId = null;

  function $(selector, root = document) {
    return root.querySelector(selector);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return dateFormatter.format(date);
  }

  function formatNumber(value) {
    if (value === null || value === undefined || value === "") return "-";
    return numberFormatter.format(Number(value));
  }

  function label(group, value) {
    return labels[group]?.[value] || value || "-";
  }

  function badge(value, group = "status") {
    const raw = String(value || "unknown");
    const text = label(group, raw);
    const kind = raw.replaceAll("_", "-");
    return `<span class="badge badge-${escapeHtml(kind)}">${escapeHtml(text)}</span>`;
  }

  function slaRiskLevel(value) {
    if (!value) return "not_applicable";
    const risk = typeof value === "string" ? value : value.sla_risk_level || value.sla_status;
    if (risk === "delayed") return "delayed";
    if (risk === "on_time") return "on_time";
    return "not_applicable";
  }

  function slaClass(value) {
    return `sla-${slaRiskLevel(value).replaceAll("_", "-")}`;
  }

  function slaBadge(value) {
    const risk = slaRiskLevel(value);
    const delay = typeof value === "object" ? Number(value.delay_minutes || 0) : 0;
    const text = risk === "delayed" && delay > 0 ? `延期 ${formatNumber(delay)} 分钟` : label("sla", risk);
    return `<span class="badge ${slaClass(value)}">${escapeHtml(text)}</span>`;
  }

  function scrollBehavior() {
    return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  }

  async function apiFetch(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const message = payload?.detail || payload?.message || `请求失败，状态码 ${response.status}`;
      throw new Error(Array.isArray(message) ? message.map((item) => item.msg || item).join("；") : message);
    }
    return payload;
  }

  function setStatus(id, message, tone = "muted") {
    const target = document.getElementById(id);
    if (!target) return;
    target.textContent = message;
    target.className = `status-line status-${tone}`;
  }

  function setButtonBusy(button, busy, busyText = "处理中…") {
    if (!button) return;
    if (busy) {
      button.dataset.originalText = button.textContent;
      button.textContent = busyText;
      button.disabled = true;
    } else {
      button.textContent = button.dataset.originalText || button.textContent;
      button.disabled = false;
    }
  }

  function setDebug(id, payload) {
    const target = document.getElementById(id);
    if (target) target.textContent = JSON.stringify(payload, null, 2);
  }

  function emptyRow(colspan, message) {
    return `<tr><td colspan="${colspan}" class="empty">${escapeHtml(message)}</td></tr>`;
  }

  function objectToQuery(params) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        query.set(key, value);
      }
    });
    return query.toString();
  }

  function toIsoFromLocal(value) {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date.toISOString();
  }

  function toLocalInputValue(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const offset = date.getTimezoneOffset() * 60000;
    return new Date(date.getTime() - offset).toISOString().slice(0, 16);
  }

  function metricCard(labelText, value) {
    return `<div class="metric"><span>${escapeHtml(labelText)}</span><strong>${escapeHtml(value ?? "-")}</strong></div>`;
  }

  function initDashboard() {
    if (!$("#metric-cards")) return;
    const refresh = $('[data-action="dashboard-refresh"]');
    refresh?.addEventListener("click", () => loadDashboard());
    $("#dataset-replay-form")?.addEventListener("submit", handleReplayStart);
    $("#dataset-select")?.addEventListener("change", () => loadSelectedDatasetSummary());
    $('[data-action="replay-step"]')?.addEventListener("click", (event) => runReplayAction("step", event.currentTarget));
    $('[data-action="replay-tick"]')?.addEventListener("click", (event) => runReplayAction("tick", event.currentTarget));
    $('[data-action="replay-pause"]')?.addEventListener("click", (event) => runReplayAction("pause", event.currentTarget));
    $('[data-action="replay-resume"]')?.addEventListener("click", (event) => runReplayAction("resume", event.currentTarget));
    loadDashboard();
    loadDatasets();
  }

  async function loadDashboard() {
    const button = $('[data-action="dashboard-refresh"]');
    setButtonBusy(button, true, "刷新中…");
    setStatus("dashboard-status", "正在加载监测报告…");
    try {
      const payload = await apiFetch("/api/monitor/report");
      const report = payload.data;
      const metrics = report.latest_schedule?.metrics || {};
      $("#metric-cards").innerHTML = [
        metricCard("排程批次", report.latest_schedule?.run_id || "-"),
        metricCard("已排订单", report.latest_schedule?.scheduled_count ?? 0),
        metricCard("阻塞订单", report.latest_schedule?.blocked_count ?? 0),
        metricCard("准时率", metrics.on_time_rate ?? "-"),
        metricCard("平均等待分钟", metrics.average_wait_minutes ?? "-"),
        metricCard("转运等待分钟", metrics.transfer_wait_minutes ?? "-"),
      ].join("");
      const byStatus = report.event_summary?.by_status || {};
      $("#event-status-cards").innerHTML = Object.entries(byStatus).length
        ? Object.entries(byStatus).map(([key, value]) => metricCard(label("status", key), value)).join("")
        : metricCard("事件总数", report.event_summary?.total || 0);
      const openEvents = report.event_summary?.open_events || [];
      $("#open-events-body").innerHTML = openEvents.length
        ? openEvents.slice(0, 20).map((item) => `
          <tr>
            <td>${escapeHtml(item.event_type)}</td>
            <td>${badge(item.severity, "status")}</td>
            <td>${escapeHtml([item.entity_type, item.entity_id].filter(Boolean).join(" / ") || "-")}</td>
            <td>${badge(item.status)}</td>
          </tr>
        `).join("")
        : emptyRow(4, "暂无待处理事件");
      setDebug("dashboard-debug", payload);
      setStatus("dashboard-status", "监测报告已更新", "success");
    } catch (error) {
      setStatus("dashboard-status", `${error.message}。请检查接口或权限配置。`, "error");
    } finally {
      setButtonBusy(button, false);
    }
  }

  async function loadDatasets() {
    const select = $("#dataset-select");
    if (!select) return;
    setStatus("replay-status", "正在加载可回放数据集…");
    try {
      const payload = await apiFetch("/api/datasets");
      const items = payload.data?.items || [];
      select.innerHTML = items.length
        ? items.map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}（${formatNumber(item.order_count)} 单）</option>`).join("")
        : '<option value="">没有可回放数据集</option>';
      renderDatasetSummary(items[0] || null);
      setStatus("replay-status", items.length ? "数据集已加载" : "未找到数据集", items.length ? "success" : "muted");
    } catch (error) {
      select.innerHTML = '<option value="">数据集加载失败</option>';
      $("#dataset-report-body").innerHTML = emptyRow(5, "数据集加载失败");
      setStatus("replay-status", `${error.message}。请检查数据集接口权限。`, "error");
    }
  }

  async function loadSelectedDatasetSummary() {
    const datasetName = $("#dataset-select")?.value;
    if (!datasetName) return;
    setStatus("replay-status", "正在加载数据集摘要…");
    try {
      const payload = await apiFetch(`/api/datasets/${encodeURIComponent(datasetName)}/summary`);
      renderDatasetSummary(payload.data);
      setStatus("replay-status", "数据集摘要已更新", "success");
    } catch (error) {
      $("#dataset-report-body").innerHTML = emptyRow(5, "数据集摘要加载失败");
      setStatus("replay-status", `${error.message}。请检查数据集名称。`, "error");
    }
  }

  function renderDatasetSummary(item) {
    $("#dataset-report-body").innerHTML = item
      ? `
        <tr>
          <td>${escapeHtml(item.name || item.dataset)}</td>
          <td>${formatNumber(item.order_count)}</td>
          <td>${formatDate(item.start_time)}</td>
          <td>${formatDate(item.end_time)}</td>
          <td>${formatNumber(item.max_route_length)}</td>
        </tr>
      `
      : emptyRow(5, "暂无数据集摘要");
  }

  async function handleReplayStart(event) {
    event.preventDefault();
    const button = event.submitter;
    const form = new FormData(event.currentTarget);
    const datasetName = form.get("dataset_name");
    if (!datasetName) {
      setStatus("replay-live-status", "请先选择数据集", "error");
      return;
    }
    setButtonBusy(button, true, "启动中…");
    setStatus("replay-live-status", "正在创建回放批次…");
    try {
      const payload = {
        speed_minutes_per_second: Number(form.get("speed_minutes_per_second") || 30),
        max_orders: Number(form.get("max_orders") || 500),
        reset_runtime: form.get("reset_runtime") === "on",
      };
      const response = await apiFetch(`/api/datasets/${encodeURIComponent(datasetName)}/replay/start`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      renderReplay(response.data, "load");
      setStatus("replay-live-status", "回放批次已创建，可单步导入或手动 Tick", "success");
      await loadDashboard();
    } catch (error) {
      setStatus("replay-live-status", `${error.message}。请检查数据集和权限配置。`, "error");
    } finally {
      setButtonBusy(button, false);
    }
  }

  async function runReplayAction(action, button) {
    if (!currentReplayRunId) {
      setStatus("replay-live-status", "请先启动回放批次", "error");
      return;
    }
    const text = { step: "导入中…", tick: "Tick 中…", pause: "暂停中…", resume: "续跑中…" }[action] || "处理中…";
    setButtonBusy(button, true, text);
    try {
      const payload = await apiFetch(`/api/datasets/replay/${encodeURIComponent(currentReplayRunId)}/${action}`, {
        method: "POST",
      });
      renderReplay(payload.data, action === "pause" ? "wait" : action === "resume" ? "wait" : "render");
      setStatus("replay-live-status", `回放状态：${label("status", payload.data.status)}，已导入 ${payload.data.imported_orders}/${payload.data.total_orders}`, "success");
      await loadDashboard();
    } catch (error) {
      setStatus("replay-live-status", `${error.message}。请检查回放状态。`, "error");
    } finally {
      setButtonBusy(button, false);
    }
  }

  function renderReplay(run, activeFlowStep = "wait") {
    if (!run) return;
    currentReplayRunId = run.id;
    const progress = run.total_orders ? `${formatNumber(run.imported_orders)} / ${formatNumber(run.total_orders)}` : "-";
    $("#replay-cards").innerHTML = [
      metricCard("回放批次", run.id || "-"),
      metricCard("状态", label("status", run.status)),
      metricCard("当前仿真时间", formatDate(run.current_simulation_time)),
      metricCard("导入进度", progress),
      metricCard("最新订单", run.latest_order_id || "-"),
      metricCard("最新排程", run.latest_schedule_run_id || "-"),
    ].join("");
    $("#replay-items-body").innerHTML = (run.items || []).length
      ? run.items.slice(0, 20).map((item) => `
        <tr>
          <td>${formatNumber(item.sequence)}</td>
          <td><code>${escapeHtml(item.original_order_id)}</code></td>
          <td>${formatDate(item.arrival_time)}</td>
          <td>${badge(item.import_status, "status")}</td>
          <td>${item.system_order_id ? `<code>${escapeHtml(item.system_order_id)}</code>` : "-"}</td>
        </tr>
      `).join("")
      : emptyRow(5, "暂无回放订单");
    renderReplayFlow(activeFlowStep, run);
  }

  function renderReplayFlow(activeStep, run) {
    const order = ["load", "wait", "import", "event", "schedule", "notify", "render"];
    const activeIndex = order.indexOf(activeStep);
    document.querySelectorAll("#replay-flow [data-flow-step]").forEach((item) => {
      const index = order.indexOf(item.dataset.flowStep);
      item.classList.toggle("is-active", index === activeIndex);
      item.classList.toggle("is-complete", index < activeIndex || run.status === "completed");
    });
  }

  function initOrders() {
    if (!$("#orders-table")) return;
    $("#order-form")?.addEventListener("submit", handleCreateOrder);
    $("#orders-filter-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      loadOrders();
    });
    $('[data-action="orders-reset"]')?.addEventListener("click", () => {
      $("#orders-filter-form").reset();
      loadOrders();
    });
    $("#orders-table-body")?.addEventListener("click", handleOrderTableAction);
    $("#order-detail")?.addEventListener("submit", handleOrderUpdate);
    loadOrders();
  }

  async function handleCreateOrder(event) {
    event.preventDefault();
    const button = event.submitter;
    setButtonBusy(button, true, "创建中…");
    setStatus("orders-create-status", "正在创建订单…");
    try {
      const form = new FormData(event.currentTarget);
      const payload = {
        order_type: form.get("order_type"),
        sample_name: form.get("sample_name"),
        sample_quantity: Number(form.get("sample_quantity")),
        certification_type: form.get("certification_type"),
      };
      const promised = toIsoFromLocal(form.get("promised_finish_time"));
      if (promised) payload.promised_finish_time = promised;
      const response = await apiFetch("/api/orders", { method: "POST", body: JSON.stringify(payload) });
      setStatus("orders-create-status", `订单 ${response.data.id} 已创建`, "success");
      event.currentTarget.reset();
      await loadOrders();
      await showOrderDetail(response.data.id);
    } catch (error) {
      setStatus("orders-create-status", `${error.message}。请检查订单字段。`, "error");
    } finally {
      setButtonBusy(button, false);
    }
  }

  function orderListParams() {
    const form = new FormData($("#orders-filter-form"));
    return {
      q: form.get("q"),
      order_type: form.get("order_type"),
      certification_type: form.get("certification_type"),
      status: form.get("status"),
      include_cancelled: form.get("include_cancelled") === "on" ? "true" : "",
      limit: 100,
      offset: 0,
    };
  }

  async function loadOrders() {
    setStatus("orders-list-status", "正在加载订单…");
    try {
      const query = objectToQuery(orderListParams());
      const payload = await apiFetch(`/api/orders?${query}`);
      const data = payload.data;
      const rows = data.items || [];
      $("#orders-table-body").innerHTML = rows.length
        ? rows.map((order) => `
          <tr>
            <td><code>${escapeHtml(order.id)}</code></td>
            <td>${badge(order.order_type, "orderType")}</td>
            <td>${escapeHtml(order.sample_name)}</td>
            <td>${formatNumber(order.sample_quantity)}</td>
            <td>${escapeHtml(label("certification", order.certification_type))}</td>
            <td>${badge(order.status)}</td>
            <td>${formatDate(order.promised_finish_time)}</td>
            <td>${formatNumber((order.detection_route || []).length)} 步</td>
            <td class="actions">
              <button type="button" data-order-action="view" data-order-id="${escapeHtml(order.id)}">查看</button>
              <button type="button" data-order-action="retest" data-order-id="${escapeHtml(order.id)}">复检</button>
              <button type="button" data-order-action="cancel" data-order-id="${escapeHtml(order.id)}" ${order.status === "cancelled" ? "disabled" : ""}>取消</button>
            </td>
          </tr>
        `).join("")
        : emptyRow(9, "没有符合条件的订单");
      setDebug("orders-debug", payload);
      setStatus("orders-list-status", `已加载 ${data.total} 条订单`, "success");
    } catch (error) {
      $("#orders-table-body").innerHTML = emptyRow(9, "订单加载失败");
      setStatus("orders-list-status", `${error.message}。请检查接口或权限配置。`, "error");
    }
  }

  function handleOrderTableAction(event) {
    const button = event.target.closest("button[data-order-action]");
    if (!button) return;
    const id = button.dataset.orderId;
    if (button.dataset.orderAction === "view") showOrderDetail(id);
    if (button.dataset.orderAction === "cancel") cancelOrder(id, button);
    if (button.dataset.orderAction === "retest") createRetestOrder(id, button);
  }

  async function showOrderDetail(orderId) {
    setStatus("orders-list-status", "正在加载订单详情…");
    try {
      const payload = await apiFetch(`/api/orders/${encodeURIComponent(orderId)}`);
      renderOrderDetail(payload.data);
      setStatus("orders-list-status", "订单详情已加载", "success");
    } catch (error) {
      setStatus("orders-list-status", `${error.message}。请检查订单是否存在。`, "error");
    }
  }

  function renderOrderDetail(order) {
    const routeRows = (order.detection_route || []).length
      ? order.detection_route.map((step) => `
        <tr>
          <td>${formatNumber(step.sequence)}</td>
          <td>${escapeHtml(step.project_type)}</td>
          <td>${escapeHtml(step.equipment_type)}</td>
          <td>${formatNumber(step.duration_minutes)} 分钟</td>
        </tr>
      `).join("")
      : emptyRow(4, "未指定订单级检测路线，将使用认证默认流程");
    $("#order-detail").innerHTML = `
      <form id="order-update-form" class="stack" autocomplete="off" data-order-id="${escapeHtml(order.id)}">
        <div class="detail-grid">
          <div><span>订单号</span><strong><code>${escapeHtml(order.id)}</code></strong></div>
          <div><span>创建时间</span><strong>${formatDate(order.created_at)}</strong></div>
          <div><span>状态</span><strong>${badge(order.status)}</strong></div>
          <div><span>父订单</span><strong>${escapeHtml(order.parent_order_id || "-")}</strong></div>
        </div>
        <label>订单类型
          <select name="order_type">
            <option value="normal" ${order.order_type === "normal" ? "selected" : ""}>普通订单</option>
            <option value="urgent" ${order.order_type === "urgent" ? "selected" : ""}>加急订单</option>
            <option value="vip" ${order.order_type === "vip" ? "selected" : ""}>VIP订单</option>
          </select>
        </label>
        <label>样品名称
          <input name="sample_name" value="${escapeHtml(order.sample_name)}" autocomplete="off" required>
        </label>
        <label>样品数量
          <input name="sample_quantity" type="number" inputmode="numeric" min="1" value="${escapeHtml(order.sample_quantity)}" required>
        </label>
        <label>状态
          <select name="status">
            ${["pending", "scheduled", "running", "completed", "blocked", "cancelled"].map((item) => `<option value="${item}" ${order.status === item ? "selected" : ""}>${label("status", item)}</option>`).join("")}
          </select>
        </label>
        <label>承诺完成时间
          <input name="promised_finish_time" type="datetime-local" value="${toLocalInputValue(order.promised_finish_time)}" autocomplete="off">
        </label>
        <button type="submit">保存订单</button>
      </form>
      <h3>检测路线</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>顺序</th><th>项目</th><th>设备类型</th><th>耗时</th></tr></thead>
          <tbody>${routeRows}</tbody>
        </table>
      </div>
      <details class="debug-panel">
        <summary>查看订单原始数据</summary>
        <pre>${escapeHtml(JSON.stringify(order, null, 2))}</pre>
      </details>
    `;
  }

  async function handleOrderUpdate(event) {
    if (event.target.id !== "order-update-form") return;
    event.preventDefault();
    const button = event.submitter;
    const form = new FormData(event.target);
    const orderId = event.target.dataset.orderId;
    const promised = toIsoFromLocal(form.get("promised_finish_time"));
    const payload = {
      order_type: form.get("order_type"),
      sample_name: form.get("sample_name"),
      sample_quantity: Number(form.get("sample_quantity")),
      status: form.get("status"),
    };
    if (promised) payload.promised_finish_time = promised;
    setButtonBusy(button, true, "保存中…");
    try {
      const response = await apiFetch(`/api/orders/${encodeURIComponent(orderId)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      renderOrderDetail(response.data);
      await loadOrders();
      setStatus("orders-list-status", "订单已保存", "success");
    } catch (error) {
      setStatus("orders-list-status", `${error.message}。请检查订单字段。`, "error");
    } finally {
      setButtonBusy(button, false);
    }
  }

  async function cancelOrder(orderId, button) {
    if (!window.confirm(`确认取消订单 ${orderId}？`)) return;
    setButtonBusy(button, true, "取消中…");
    try {
      await apiFetch(`/api/orders/${encodeURIComponent(orderId)}`, { method: "DELETE" });
      await loadOrders();
      $("#order-detail").innerHTML = '<div class="empty">订单已取消。请从列表选择其他记录。</div>';
      setStatus("orders-list-status", "订单已取消", "success");
    } catch (error) {
      setStatus("orders-list-status", `${error.message}。请检查权限或订单状态。`, "error");
    } finally {
      setButtonBusy(button, false);
    }
  }

  async function createRetestOrder(orderId, button) {
    const reason = window.prompt("请输入复检原因");
    if (!reason) return;
    setButtonBusy(button, true, "创建中…");
    try {
      const response = await apiFetch(`/api/orders/${encodeURIComponent(orderId)}/retest`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
      await loadOrders();
      await showOrderDetail(response.data.id);
      setStatus("orders-list-status", "复检订单已创建", "success");
    } catch (error) {
      setStatus("orders-list-status", `${error.message}。请检查复检参数。`, "error");
    } finally {
      setButtonBusy(button, false);
    }
  }

  function initQueue() {
    if (!$("#steps-table")) return;
    $('[data-action="queue-load"]')?.addEventListener("click", () => loadQueue());
    $('[data-action="queue-rebuild"]')?.addEventListener("click", (event) => rebuildQueue(event.currentTarget));
    $('[data-action="queue-options"]')?.addEventListener("click", (event) => loadScheduleOptions(event.currentTarget));
    $("#steps-table-body")?.addEventListener("click", handleScheduleStepSelection);
    $("#gantt")?.addEventListener("click", handleScheduleStepSelection);
    loadQueue();
  }

  async function loadQueue() {
    setStatus("queue-status", "正在加载最新队列…");
    try {
      const payload = await apiFetch("/api/queue");
      renderQueue(payload.data);
      setDebug("queue-debug", payload);
      setStatus("queue-status", "最新队列已加载", "success");
    } catch (error) {
      setStatus("queue-status", `${error.message}。请检查排程是否已生成。`, "error");
    }
  }

  async function rebuildQueue(button) {
    setButtonBusy(button, true, "重建中…");
    setStatus("queue-status", "正在重建队列…");
    try {
      const payload = await apiFetch("/api/queue/rebuild", { method: "POST" });
      renderQueue(payload.data);
      setDebug("queue-debug", payload);
      setStatus("queue-status", "队列重建完成", "success");
    } catch (error) {
      setStatus("queue-status", `${error.message}。请检查排程权限或事件状态。`, "error");
    } finally {
      setButtonBusy(button, false);
    }
  }

  async function loadScheduleOptions(button) {
    setButtonBusy(button, true, "比较中…");
    setStatus("queue-status", "正在比较候选策略…");
    try {
      const payload = await apiFetch("/api/agent/run", {
        method: "POST",
        body: JSON.stringify({ task_type: "analyze_schedule_options", payload: {} }),
      });
      renderStrategyTable(payload.data?.analysis || {});
      setDebug("queue-debug", payload);
      setStatus("queue-status", "策略对比已更新", "success");
    } catch (error) {
      setStatus("queue-status", `${error.message}。请检查 Agent 权限。`, "error");
    } finally {
      setButtonBusy(button, false);
    }
  }

  function renderQueue(data) {
    const metrics = data.metrics || {};
    $("#queue-metrics").innerHTML = [
      metricCard("排程批次", data.run_id || data.id || "-"),
      metricCard("已排订单", data.scheduled_count ?? (data.scheduled_orders || []).length),
      metricCard("阻塞订单", data.blocked_count ?? (data.blocked_orders || []).length),
      metricCard("选中策略", metrics.selected_strategy || "-"),
      metricCard("准时率", metrics.on_time_rate ?? "-"),
      metricCard("平均等待分钟", metrics.average_wait_minutes ?? "-"),
      metricCard("SLA 延期分钟", metrics.total_delay_minutes ?? 0),
    ].join("");
    renderStrategyTable({ selected_strategy: metrics.selected_strategy, candidate_scores: metrics.candidate_scores });
    renderSteps(data.scheduled_orders || []);
    renderBlockedOrders(data.blocked_orders || []);
    renderGantt(data.gantt);
    renderSelectedStepDetail(null);
  }

  function renderStrategyTable(analysis) {
    const scores = analysis?.candidate_scores || {};
    const candidates = analysis?.candidates || {};
    const selected = analysis?.selected_strategy;
    const rows = Object.entries(scores);
    $("#strategy-table-body").innerHTML = rows.length
      ? rows.map(([strategy, score]) => {
        const candidate = candidates[strategy] || {};
        const metrics = candidate.metrics || {};
        return `
          <tr class="${strategy === selected ? "is-selected" : ""}">
            <td>${escapeHtml(strategy)}${strategy === selected ? " " + badge("selected", "status") : ""}</td>
            <td>${formatNumber(score)}</td>
            <td>${formatNumber(candidate.scheduled_count)}</td>
            <td>${formatNumber(candidate.blocked_count)}</td>
            <td>${formatNumber(metrics.on_time_rate)}</td>
            <td>${formatNumber(metrics.average_wait_minutes)}</td>
          </tr>
        `;
      }).join("")
      : emptyRow(6, "暂无策略评分");
  }

  function renderSteps(orders) {
    const steps = [];
    orders.forEach((order) => {
      (order.steps || []).forEach((step) => steps.push({ order, step }));
    });
    currentScheduleSteps = new Map(steps.map((item) => [item.step.id, item]));
    $("#steps-table-body").innerHTML = steps.length
      ? steps.map(({ order, step }) => `
        <tr id="step-row-${escapeHtml(step.id)}" class="${slaClass(step)}" data-step-id="${escapeHtml(step.id)}">
          <td>${formatNumber(step.position || step.sequence)}</td>
          <td><code>${escapeHtml(order.id)}</code><br>${escapeHtml(order.sample_name)}</td>
          <td>${slaBadge(step)}</td>
          <td>${badge(step.step_kind, "stepKind")}<br>${escapeHtml(step.project_type || "-")}</td>
          <td>${escapeHtml(step.equipment_id || (step.resource_ids || []).join(", ") || step.equipment_type || "-")}</td>
          <td>${escapeHtml((step.assigned_employee_ids || []).join(", ") || "-")}</td>
          <td>${formatDate(step.start_time)}</td>
          <td>${formatDate(step.end_time)}</td>
          <td>${badge(step.execution_status || order.status)}${step.locked ? " " + badge("locked", "status") : ""}</td>
          <td><button type="button" data-step-id="${escapeHtml(step.id)}">定位</button></td>
        </tr>
      `).join("")
      : emptyRow(10, "暂无排程步骤");
  }

  function renderBlockedOrders(orders) {
    $("#blocked-orders-body").innerHTML = orders.length
      ? orders.map((order) => `
        <tr>
          <td><code>${escapeHtml(order.id)}</code></td>
          <td>${badge(order.order_type, "orderType")}</td>
          <td>${escapeHtml(order.sample_name)}</td>
          ${renderBlockedReasonDetail(order.reason_detail, order.reason)}
        </tr>
      `).join("")
      : emptyRow(6, "暂无阻塞订单");
  }

  function renderBlockedReasonDetail(detail, fallbackReason) {
    const safeDetail = detail || {
      category: "unknown",
      summary: fallbackReason || "-",
      suggested_action: "查看订单路线、资源约束和排程事件日志。",
    };
    return `
      <td>${escapeHtml(safeDetail.category || "unknown")}</td>
      <td>${escapeHtml(safeDetail.summary || fallbackReason || "-")}</td>
      <td>${escapeHtml(safeDetail.suggested_action || "-")}</td>
    `;
  }

  function renderGantt(gantt) {
    const target = $("#gantt");
    if (!target) return;
    if (!gantt || !gantt.rows || !gantt.rows.length || !gantt.bars || !gantt.bars.length) {
      target.innerHTML = '<div class="empty">暂无甘特图数据</div>';
      return;
    }
    const times = gantt.bars.map((item) => [Date.parse(item.start_time), Date.parse(item.end_time)]).flat();
    const min = Math.min(...times);
    const max = Math.max(...times);
    const span = Math.max(1, max - min);
    target.innerHTML = gantt.rows.map((row) => `
      <div class="gantt-row">
        <div class="gantt-label">${escapeHtml(row.resource_id)}</div>
        <div class="gantt-line" role="group" aria-label="${escapeHtml(row.resource_id)} 的排程">
          ${row.bars.map((bar) => {
            const left = ((Date.parse(bar.start_time) - min) / span) * 100;
            const width = Math.max(2, ((Date.parse(bar.end_time) - Date.parse(bar.start_time)) / span) * 100);
            const text = `${bar.order_id} ${bar.project_type || bar.step_kind || ""}`.trim();
            const aria = `${text}，${formatDate(bar.start_time)} 到 ${formatDate(bar.end_time)}`;
            return `<button type="button" class="gantt-bar ${bar.locked ? "locked" : ""} ${slaClass(bar)}" data-step-id="${escapeHtml(bar.id)}" aria-pressed="false" aria-label="${escapeHtml(aria)}" style="left:${left}%;width:${width}%;"><span>${escapeHtml(text)}</span></button>`;
          }).join("")}
        </div>
      </div>
    `).join("");
  }

  function handleScheduleStepSelection(event) {
    const target = event.target.closest("[data-step-id]");
    if (!target) return;
    highlightScheduleStep(target.dataset.stepId);
  }

  function highlightScheduleStep(stepId) {
    const record = currentScheduleSteps.get(stepId);
    document.querySelectorAll("[data-step-id]").forEach((element) => {
      const active = element.dataset.stepId === stepId;
      element.classList.toggle("is-active-step", active);
      if (element.matches(".gantt-bar")) {
        element.setAttribute("aria-pressed", active ? "true" : "false");
      }
    });
    renderSelectedStepDetail(record || null);
    const row = document.getElementById(`step-row-${stepId}`);
    row?.scrollIntoView({ block: "nearest", behavior: scrollBehavior() });
  }

  function renderSelectedStepDetail(record) {
    const target = $("#selected-step-detail");
    if (!target) return;
    if (!record) {
      target.innerHTML = '<div class="empty">点击甘特条或步骤表中的“定位”查看详情。</div>';
      return;
    }
    const { order, step } = record;
    target.innerHTML = `
      <div class="detail-grid">
        <div><span>订单</span><strong><code>${escapeHtml(order.id)}</code></strong></div>
        <div><span>样品</span><strong>${escapeHtml(order.sample_name)}</strong></div>
        <div><span>SLA 风险</span><strong>${slaBadge(step)}</strong></div>
        <div><span>步骤状态</span><strong>${badge(step.execution_status || order.status)}</strong></div>
        <div><span>步骤</span><strong>${escapeHtml(label("stepKind", step.step_kind))} / ${escapeHtml(step.project_type || "-")}</strong></div>
        <div><span>设备或资源</span><strong>${escapeHtml(step.equipment_id || (step.resource_ids || []).join(", ") || step.equipment_type || "-")}</strong></div>
        <div><span>员工</span><strong>${escapeHtml((step.assigned_employee_ids || []).join(", ") || "-")}</strong></div>
        <div><span>时间窗口</span><strong>${formatDate(step.start_time)} 到 ${formatDate(step.end_time)}</strong></div>
      </div>
      <details class="debug-panel" open>
        <summary>查看约束明细</summary>
        <pre>${escapeHtml(JSON.stringify(step.constraint_detail || {}, null, 2))}</pre>
      </details>
    `;
  }

  function initNotifications() {
    if (!$("#notifications-table-body")) return;
    $("#notifications-filter-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      loadNotifications();
    });
    $('[data-action="notifications-reset"]')?.addEventListener("click", () => {
      $("#notifications-filter-form").reset();
      loadNotifications();
    });
    $('[data-action="notifications-clock"]')?.addEventListener("click", (event) => advanceClock(event.currentTarget));
    $("#notifications-table-body")?.addEventListener("click", handleNotificationAction);
    connectNotificationStream();
    loadNotifications();
  }

  function notificationParams() {
    const form = new FormData($("#notifications-filter-form"));
    return {
      status: form.get("status"),
      notification_type: form.get("notification_type"),
    };
  }

  async function loadNotifications() {
    setStatus("notifications-status", "正在加载通知…");
    try {
      const query = objectToQuery(notificationParams());
      const payload = await apiFetch(`/api/notifications${query ? "?" + query : ""}`);
      const notifications = payload.data || [];
      $("#notifications-table-body").innerHTML = notifications.length
        ? notifications.map((item) => `
          <tr>
            <td><strong>${escapeHtml(item.title)}</strong><br><span class="muted">${escapeHtml(item.message)}</span></td>
            <td>${badge(item.severity, "status")}</td>
            <td>${escapeHtml(label("notificationType", item.notification_type))}</td>
            <td>${badge(item.status)}</td>
            <td>${escapeHtml([item.order_id, item.related_resource_id].filter(Boolean).join(" / ") || "-")}</td>
            <td>${formatDate(item.planned_trigger_time)}</td>
            <td>${formatDate(item.triggered_at)}</td>
            <td class="actions">
              <button type="button" data-notification-action="read" data-notification-id="${escapeHtml(item.id)}" ${item.status === "read" ? "disabled" : ""}>标记已读</button>
            </td>
          </tr>
        `).join("")
        : emptyRow(8, "没有符合条件的通知");
      setDebug("notifications-debug", payload);
      setStatus("notifications-status", `已加载 ${notifications.length} 条通知`, "success");
    } catch (error) {
      $("#notifications-table-body").innerHTML = emptyRow(8, "通知加载失败");
      setStatus("notifications-status", `${error.message}。请检查通知权限。`, "error");
    }
  }

  function handleNotificationAction(event) {
    const button = event.target.closest("button[data-notification-action]");
    if (!button) return;
    markNotificationRead(button.dataset.notificationId, button);
  }

  async function markNotificationRead(id, button) {
    setButtonBusy(button, true, "处理中…");
    try {
      await apiFetch(`/api/notifications/${encodeURIComponent(id)}/read`, { method: "PATCH" });
      await loadNotifications();
      setStatus("notifications-status", "通知已标记为已读", "success");
    } catch (error) {
      setStatus("notifications-status", `${error.message}。请检查通知状态。`, "error");
    } finally {
      setButtonBusy(button, false);
    }
  }

  async function advanceClock(button) {
    setButtonBusy(button, true, "推进中…");
    try {
      const payload = await apiFetch("/api/simulation/clock/advance", {
        method: "POST",
        body: JSON.stringify({ delta_minutes: 30 }),
      });
      setDebug("notifications-debug", payload);
      await loadNotifications();
      setStatus("notifications-status", "仿真时钟已推进", "success");
    } catch (error) {
      setStatus("notifications-status", `${error.message}。请检查仿真时钟接口。`, "error");
    } finally {
      setButtonBusy(button, false);
    }
  }

  function connectNotificationStream() {
    const status = $("#sse-status");
    if (!status || !window.EventSource) return;
    const stream = new EventSource("/api/notifications/stream");
    stream.onopen = () => {
      status.textContent = "实时连接已建立";
      status.className = "badge badge-success";
    };
    stream.onmessage = () => {
      status.textContent = "收到实时通知";
      loadNotifications();
    };
    stream.onerror = () => {
      status.textContent = "实时连接已断开";
      status.className = "badge badge-error";
      stream.close();
    };
  }

  function initKnowledge() {
    if (!$("#knowledge-form")) return;
    $("#knowledge-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = event.submitter;
      setButtonBusy(button, true, "检索中…");
      setStatus("knowledge-status", "正在检索知识库…");
      try {
        const query = new FormData(event.currentTarget).get("query");
        const payload = await apiFetch("/api/knowledge/search", {
          method: "POST",
          body: JSON.stringify({ query, top_k: 3 }),
        });
        const results = payload.data?.results || payload.data || [];
        $("#knowledge-results").innerHTML = Array.isArray(results) && results.length
          ? results.map((item) => `
            <article class="result-item">
              <h2>${escapeHtml(item.source || "知识片段")}</h2>
              <p>${escapeHtml(item.content || item.text || "")}</p>
              <span class="muted">分数：${formatNumber(item.score)}</span>
            </article>
          `).join("")
          : '<div class="empty">没有检索命中。</div>';
        setDebug("knowledge-debug", payload);
        setStatus("knowledge-status", "检索完成", "success");
      } catch (error) {
        setStatus("knowledge-status", `${error.message}。请检查查询内容。`, "error");
      } finally {
        setButtonBusy(button, false);
      }
    });
    $('[data-action="knowledge-reindex"]')?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      setButtonBusy(button, true, "重建中…");
      try {
        const payload = await apiFetch("/api/knowledge/reindex", { method: "POST" });
        setDebug("knowledge-debug", payload);
        setStatus("knowledge-status", "索引已重建", "success");
      } catch (error) {
        setStatus("knowledge-status", `${error.message}。请检查 embedding 配置。`, "error");
      } finally {
        setButtonBusy(button, false);
      }
    });
  }

  function initAgents() {
    if (!$("#agent-form")) return;
    $("#agent-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = event.submitter;
      const taskType = new FormData(event.currentTarget).get("task_type");
      setButtonBusy(button, true, "运行中…");
      setStatus("agent-status", "正在运行 Agent…");
      try {
        const payload = await apiFetch("/api/agent/run", {
          method: "POST",
          body: JSON.stringify({ task_type: taskType, payload: {} }),
        });
        const data = payload.data || {};
        $("#agent-visited").innerHTML = (data.visited_agents || []).length
          ? data.visited_agents.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
          : '<li class="empty">没有节点访问记录</li>';
        $("#agent-handoffs").innerHTML = (data.handoffs || []).length
          ? data.handoffs.map((item) => `
            <article class="result-item">
              <h2>${escapeHtml(item.source)} 到 ${escapeHtml(item.target)}</h2>
              <p>${escapeHtml(item.reason)}</p>
            </article>
          `).join("")
          : '<div class="empty">没有 handoff 记录。</div>';
        setDebug("agent-debug", payload);
        setStatus("agent-status", "Agent 任务完成", "success");
      } catch (error) {
        setStatus("agent-status", `${error.message}。请检查任务权限。`, "error");
      } finally {
        setButtonBusy(button, false);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initDashboard();
    initOrders();
    initQueue();
    initNotifications();
    initKnowledge();
    initAgents();
  });
})();
