const $ = (selector) => document.querySelector(selector);
let page = 1;
let pages = 1;
let busy = false;

const fmt = (value) => value
  ? new Date(value).toLocaleString("zh-CN", { hour12: false })
  : "—";

const esc = (value) => String(value ?? "").replace(
  /[&<>"']/g,
  (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]),
);

function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.className = error ? "show error" : "show";
  setTimeout(() => { element.className = ""; }, 2800);
}

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}

function fillSelect(element, label, values) {
  const current = element.value;
  element.innerHTML = `<option value="">${label}</option>${values.map(
    (value) => `<option value="${esc(value)}">${esc(value)}</option>`,
  ).join("")}`;
  element.value = current;
}

async function loadStats() {
  const stats = await api("/api/stats");
  $("#total").textContent = stats.total || 0;
  $("#heroCount").textContent = stats.total || 0;
  $("#brands").textContent = stats.brands || 0;
  $("#available").textContent = stats.available || 0;
  $("#promoted").textContent = stats.promoted || 0;
  $("#heroTime").textContent = stats.updated_at ? fmt(stats.updated_at) : "尚未采集";
  fillSelect($("#brand"), "全部品牌", stats.brands_list || []);
  fillSelect($("#category"), "全部分类", stats.categories_list || []);
}

function card(product) {
  const tags = product.promotion_tags || [];
  const category = product.category_path || product.category_name || "分类待补充";
  const stockClass = !product.is_sellable || !product.stock_count ? "out" : "";
  const stockText = product.is_sellable && product.stock_count > 0
    ? `库存 ${product.stock_count}`
    : "暂不可售";
  return `<article class="product-card">
    <a class="product-image" href="${esc(product.product_url)}" target="_blank" rel="noreferrer">
      ${tags[0] ? `<span class="tag">${esc(tags[0])}</span>` : ""}
      ${product.image_url
        ? `<img src="${esc(product.image_url)}" alt="${esc(product.name)}" loading="lazy">`
        : "<span>暂无图片</span>"}
    </a>
    <div class="product-body">
      <div class="brand-name">${esc(product.brand || "其他品牌")}${product.brand_en ? ` · ${esc(product.brand_en)}` : ""}</div>
      <h3>${esc(product.name)}</h3>
      <div class="spec" title="${esc(category)}">${esc(category)} · ${esc(product.spec || product.product_code || "")}</div>
      <div class="price-row">
        <div class="price"><small>¥</small>${product.price == null ? "—" : Number(product.price).toFixed(2)}</div>
        <span class="stock ${stockClass}">${stockText}</span>
      </div>
      <div class="card-meta"><span>${esc(product.price_label)}</span><span>网站公开销量 ${product.public_sales_count ?? "—"}</span></div>
    </div>
  </article>`;
}

async function loadProducts(reset = false) {
  if (reset) page = 1;
  const query = new URLSearchParams({
    q: $("#search").value,
    brand: $("#brand").value,
    category: $("#category").value,
    stock: $("#stock").value,
    sort: $("#sort").value,
    page,
    page_size: 24,
  });
  $("#catalog").innerHTML = '<div class="loading">正在读取商品数据…</div>';
  try {
    const data = await api(`/api/products?${query}`);
    pages = Math.max(1, data.pages);
    $("#catalog").innerHTML = data.items.length
      ? data.items.map(card).join("")
      : '<div class="empty">暂无符合条件的商品。点击“立即采集”建立第一份数据快照。</div>';
    $("#pageInfo").textContent = `第 ${page} / ${pages} 页 · 共 ${data.total} 条`;
    $("#prev").disabled = page <= 1;
    $("#next").disabled = page >= pages;
  } catch (error) {
    $("#catalog").innerHTML = `<div class="empty">读取失败：${esc(error.message)}</div>`;
  }
}

async function loadActivity() {
  const [history, changes] = await Promise.all([api("/api/history"), api("/api/changes")]);
  $("#history").innerHTML = history.runs.length
    ? history.runs.map((run) => `<div class="row"><time>${fmt(run.started_at)}</time><span class="badge ${run.status}">${({ success: "成功", failed: "失败", running: "进行中" })[run.status] || run.status}</span><small>${run.found_count} 条 · +${run.added_count} / 变更 ${run.updated_count}</small></div>`).join("")
    : '<div class="empty">暂无商品采集记录</div>';
  $("#changes").innerHTML = changes.changes.length
    ? changes.changes.map((change) => `<div class="row"><time>${fmt(change.changed_at)}</time><span>${esc(change.product_name)}</span><small>${change.change_type === "added" ? "新增" : "更新"}</small></div>`).join("")
    : '<div class="empty">暂无商品变更</div>';
}

async function refresh() {
  if (busy) return;
  busy = true;
  const button = $("#refresh");
  button.disabled = true;
  button.textContent = "采集中…";
  try {
    const started = await api("/api/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_pages: 5, page_size: 20, delay: 1.2, has_stock: true }),
    });
    toast("采集任务已启动");
    let done = false;
    for (let attempt = 0; attempt < 90 && !done; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      const health = await api("/api/health");
      const run = health.latest_run;
      done = run && run.id === started.run_id && run.status !== "running";
      if (done && run.status === "failed") throw new Error(run.error || "采集失败");
    }
    if (!done) {
      toast("任务仍在后台运行，请稍后刷新");
    } else {
      await Promise.all([loadStats(), loadProducts(true), loadActivity()]);
      toast("商品快照已更新");
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    busy = false;
    button.disabled = false;
    button.textContent = "立即采集 5 页";
  }
}

async function loadSchedule() {
  const schedule = await api("/api/schedule");
  $("#enabled").checked = schedule.enabled;
  $("#interval").value = schedule.interval_hours;
  $("#nextRun").textContent = fmt(schedule.next_run_at);
}

async function saveSchedule() {
  try {
    const schedule = await api("/api/schedule", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: $("#enabled").checked,
        interval_hours: Number($("#interval").value),
      }),
    });
    $("#nextRun").textContent = fmt(schedule.next_run_at);
    toast("自动采集设置已保存");
  } catch (error) {
    toast(error.message, true);
  }
}

let searchTimer;
$("#search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadProducts(true), 300);
});
["brand", "category", "stock", "sort"].forEach((id) => {
  $(`#${id}`).addEventListener("change", () => loadProducts(true));
});
$("#prev").onclick = () => { if (page > 1) { page -= 1; loadProducts(); } };
$("#next").onclick = () => { if (page < pages) { page += 1; loadProducts(); } };
$("#refresh").onclick = refresh;
$("#saveSchedule").onclick = saveSchedule;

Promise.all([loadStats(), loadProducts(), loadActivity(), loadSchedule()])
  .catch((error) => toast(error.message, true));

