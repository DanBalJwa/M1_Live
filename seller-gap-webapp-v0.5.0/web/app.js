"use strict";

const state = {
  categories: {},
  settings: null,
  rows: [],
  activeTab: "naver",
  selectedPath: [],
  currentDetail: null,
};

const $ = (id) => document.getElementById(id);
const qsAll = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatNumber(value, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("ko-KR") : fallback;
}

function formatWon(value) {
  return value === null || value === undefined ? "-" : `${formatNumber(value)}원`;
}

function formatPercent(value) {
  return value === null || value === undefined ? "-" : `${Number(value).toFixed(1)}%`;
}

function trendClass(value) {
  if (value === null || value === undefined) return "muted";
  return Number(value) > 0 ? "good" : Number(value) < 0 ? "bad" : "muted";
}

function get(object, path, fallback = null) {
  let current = object;
  for (const key of path.split(".")) {
    if (current === null || current === undefined || !(key in current)) return fallback;
    current = current[key];
  }
  return current ?? fallback;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`서버 응답을 읽지 못했습니다. HTTP ${response.status}`);
  }
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function setStatus(message, type = "info") {
  const box = $("statusBox");
  box.className = `status ${type}`;
  box.textContent = message;
}

function setDetailStatus(message, type = "info") {
  const box = $("detailStatus");
  box.className = `status ${type}`;
  box.textContent = message;
}

function openModal(id) {
  const modal = $(id);
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

function closeModal(id) {
  const modal = $(id);
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

function childrenOf(node) {
  return node && typeof node.children === "object" ? node.children : {};
}

function categoryNode(path) {
  let children = state.categories;
  let node = null;
  for (const name of path) {
    node = children[name];
    if (!node) return null;
    children = childrenOf(node);
  }
  return node;
}

function setSelectOptions(select, names, placeholder) {
  select.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>` +
    names.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
  select.disabled = names.length === 0;
}

function resetSelect(index) {
  for (let i = index; i <= 4; i += 1) {
    const select = $(`cat${i}`);
    setSelectOptions(select, [], `${i}차 분류`);
  }
}

function initializeCategorySelectors() {
  setSelectOptions($("cat1"), Object.keys(state.categories), "1차 분류");
  $("cat1").disabled = false;
  [1, 2, 3, 4].forEach((level) => {
    $(`cat${level}`).addEventListener("change", () => handleCategoryChange(level));
  });
}

function handleCategoryChange(level) {
  const path = [];
  for (let i = 1; i <= level; i += 1) {
    const value = $(`cat${i}`).value;
    if (value) path.push(value);
  }
  state.selectedPath = path;
  if (level < 4) {
    resetSelect(level + 1);
    const node = categoryNode(path);
    const names = Object.keys(childrenOf(node));
    if (names.length) {
      setSelectOptions($(`cat${level + 1}`), names, `${level + 1}차 분류`);
      $(`cat${level + 1}`).disabled = false;
    }
  }
}

function currentPath() {
  const path = [];
  for (let i = 1; i <= 4; i += 1) {
    const value = $(`cat${i}`).value;
    if (value) path.push(value);
    else break;
  }
  return path;
}

function monthlySearch(row) {
  const exact = get(row, "naver.searchVolume.exact");
  return exact ? exact.monthlyTotal : null;
}

function monthlySearchDisplay(row) {
  const exact = get(row, "naver.searchVolume.exact");
  return exact ? exact.monthlyTotalDisplay : "미설정";
}

function coupangProducts(row) {
  return get(row, "coupang.products", {});
}

function naverProducts(row) {
  return get(row, "naver.products", {});
}

function filteredRows() {
  const keyword = $("filterKeyword").value.trim().toLowerCase();
  const searchMin = Number($("filterSearchMin").value || 0);
  const coupangPriceMax = Number($("filterCoupangPriceMax").value || 0);
  const rocketMin = Number($("filterRocketMin").value || 0);
  const reviewMax = Number($("filterReviewMax").value || 0);
  const limit = Number($("rowLimit").value || 20);

  return state.rows.filter((row) => {
    if (keyword && !row.keyword.toLowerCase().includes(keyword)) return false;
    const search = monthlySearch(row);
    if (searchMin && (search === null || search < searchMin)) return false;
    const cp = coupangProducts(row);
    if (coupangPriceMax && (get(cp, "prices.avg") === null || get(cp, "prices.avg") > coupangPriceMax)) return false;
    if (rocketMin && (get(cp, "delivery.rocketRatio") === null || get(cp, "delivery.rocketRatio") < rocketMin)) return false;
    if (reviewMax && (get(cp, "reviews.avg") === null || get(cp, "reviews.avg") > reviewMax)) return false;
    return true;
  }).slice(0, limit);
}

function keywordButton(row) {
  return `<button class="keyword-link" data-keyword="${encodeURIComponent(row.keyword)}" data-category="${encodeURIComponent(JSON.stringify(row.categoryPath || []))}" data-code="${escapeHtml(row.categoryCode || "")}">${escapeHtml(row.keyword)}</button>`;
}

function sourceNote(products) {
  if (!products || !products.source) return "";
  return `<span class="source-note">${escapeHtml(products.sampleNotice || products.source)}</span>`;
}

function renderNaverTable(rows) {
  return `
    <table class="data-table">
      <thead><tr>
        <th>키워드</th><th>카테고리</th>
        <th class="naver-head">월 검색량</th>
        <th class="naver-head">통합검색 최근지수</th>
        <th class="naver-head">최근 3개월 증감</th>
        <th class="naver-head">쇼핑 클릭 최근지수</th>
        <th class="naver-head">클릭 3개월 증감</th>
        <th class="naver-head">계절성</th>
        <th class="naver-head">검색 상품 수</th>
        <th class="naver-head">표본 수</th>
        <th class="naver-head">최저가</th>
        <th class="naver-head">중앙가</th>
        <th class="naver-head">평균가</th>
        <th>상태</th>
      </tr></thead>
      <tbody>${rows.map((row) => {
        const searchTrend = get(row, "naver.searchTrend", {});
        const clickTrend = get(row, "naver.shoppingClickTrend", {});
        const products = naverProducts(row);
        const errors = [searchTrend.error, clickTrend.error, products.error].filter(Boolean).join(" / ");
        return `<tr>
          <td class="keyword-cell">${keywordButton(row)}</td>
          <td class="category-cell">${escapeHtml((row.categoryPath || []).join(" > "))}</td>
          <td class="number">${escapeHtml(monthlySearchDisplay(row))}</td>
          <td class="number">${formatNumber(searchTrend.latest)}</td>
          <td class="number ${trendClass(searchTrend.change3m)}">${formatPercent(searchTrend.change3m)}</td>
          <td class="number">${formatNumber(clickTrend.latest)}</td>
          <td class="number ${trendClass(clickTrend.change3m)}">${formatPercent(clickTrend.change3m)}</td>
          <td>${escapeHtml(clickTrend.seasonality || searchTrend.seasonality || "-")}</td>
          <td class="number">${formatNumber(products.reportedTotal)}</td>
          <td class="number">${formatNumber(products.sampleCount)}${sourceNote(products)}</td>
          <td class="number">${formatWon(get(products, "prices.min"))}</td>
          <td class="number">${formatWon(get(products, "prices.median"))}</td>
          <td class="number">${formatWon(get(products, "prices.avg"))}</td>
          <td class="note-cell ${errors ? "bad" : "good"}">${escapeHtml(errors || "조회 완료")}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
}

function renderCoupangTable(rows) {
  return `
    <table class="data-table">
      <thead><tr>
        <th>키워드</th><th>카테고리</th>
        <th class="coupang-head">표본 상품 수</th>
        <th class="coupang-head">최저가</th>
        <th class="coupang-head">중앙가</th>
        <th class="coupang-head">평균가</th>
        <th class="coupang-head">총 리뷰</th>
        <th class="coupang-head">최대 리뷰</th>
        <th class="coupang-head">평균 리뷰</th>
        <th class="coupang-head">로켓배송</th>
        <th class="coupang-head">판매자로켓</th>
        <th class="coupang-head">일반배송</th>
        <th class="coupang-head">해외배송</th>
        <th class="coupang-head">광고 비율</th>
        <th>수집 범위·상태</th>
      </tr></thead>
      <tbody>${rows.map((row) => {
        const products = coupangProducts(row);
        return `<tr>
          <td class="keyword-cell">${keywordButton(row)}</td>
          <td class="category-cell">${escapeHtml((row.categoryPath || []).join(" > "))}</td>
          <td class="number">${formatNumber(products.sampleCount)}</td>
          <td class="number">${formatWon(get(products, "prices.min"))}</td>
          <td class="number">${formatWon(get(products, "prices.median"))}</td>
          <td class="number">${formatWon(get(products, "prices.avg"))}</td>
          <td class="number">${formatNumber(get(products, "reviews.total"), "0")}</td>
          <td class="number">${formatNumber(get(products, "reviews.max"))}</td>
          <td class="number">${formatNumber(get(products, "reviews.avg"))}</td>
          <td class="number">${formatPercent(get(products, "delivery.rocketRatio"))}</td>
          <td class="number">${formatPercent(get(products, "delivery.sellerRocketRatio"))}</td>
          <td class="number">${formatPercent(get(products, "delivery.normalRatio"))}</td>
          <td class="number">${formatPercent(get(products, "delivery.overseasRatio"))}</td>
          <td class="number">${formatPercent(get(products, "ads.ratio"))}</td>
          <td class="note-cell ${products.error ? "bad" : ""}">${escapeHtml(products.error || products.sampleNotice || "-")} ${sourceNote(products)}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
}

function renderCompareTable(rows) {
  return `
    <table class="data-table">
      <thead><tr>
        <th>키워드</th><th>카테고리</th>
        <th class="naver-head">네이버 월 검색량</th>
        <th class="naver-head">네이버 상품 수</th>
        <th class="naver-head">네이버 평균가</th>
        <th class="coupang-head">쿠팡 표본 수</th>
        <th class="coupang-head">쿠팡 평균가</th>
        <th class="coupang-head">쿠팡 총 리뷰</th>
        <th class="coupang-head">쿠팡 최대 리뷰</th>
        <th class="coupang-head">로켓+판매자로켓</th>
        <th>가격 차이</th>
        <th>판단 메모</th>
      </tr></thead>
      <tbody>${rows.map((row) => {
        const np = naverProducts(row);
        const cp = coupangProducts(row);
        const naverAvg = get(np, "prices.avg");
        const coupangAvg = get(cp, "prices.avg");
        const priceGap = naverAvg !== null && coupangAvg !== null ? coupangAvg - naverAvg : null;
        const rocket = (get(cp, "delivery.rocketRatio", 0) || 0) + (get(cp, "delivery.sellerRocketRatio", 0) || 0);
        let memo = "표본 확인 필요";
        if (get(cp, "sampleCount", 0) >= 20 && get(cp, "reviews.avg", 0) < 100 && rocket < 45) memo = "쿠팡 경쟁이 상대적으로 약할 가능성";
        else if (get(cp, "reviews.avg", 0) >= 1000 || rocket >= 75) memo = "쿠팡 상위상품 경쟁 강함";
        return `<tr>
          <td class="keyword-cell">${keywordButton(row)}</td>
          <td class="category-cell">${escapeHtml((row.categoryPath || []).join(" > "))}</td>
          <td class="number">${escapeHtml(monthlySearchDisplay(row))}</td>
          <td class="number">${formatNumber(np.reportedTotal)}</td>
          <td class="number">${formatWon(naverAvg)}</td>
          <td class="number">${formatNumber(cp.sampleCount)}</td>
          <td class="number">${formatWon(coupangAvg)}</td>
          <td class="number">${formatNumber(get(cp, "reviews.total"), "0")}</td>
          <td class="number">${formatNumber(get(cp, "reviews.max"))}</td>
          <td class="number">${formatPercent(rocket)}</td>
          <td class="number ${priceGap > 0 ? "good" : priceGap < 0 ? "bad" : ""}">${priceGap === null ? "-" : `${priceGap > 0 ? "+" : ""}${formatNumber(priceGap)}원`}</td>
          <td class="note-cell">${escapeHtml(memo)}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
}

function renderTable() {
  const rows = filteredRows();
  $("resultMeta").textContent = `전체 ${state.rows.length.toLocaleString()}개 · 표시 ${rows.length.toLocaleString()}개`;
  if (!rows.length) {
    $("tableWrap").innerHTML = `<div class="empty-state">필터 조건에 맞는 결과가 없습니다.</div>`;
    return;
  }
  if (state.activeTab === "naver") $("tableWrap").innerHTML = renderNaverTable(rows);
  else if (state.activeTab === "coupang") $("tableWrap").innerHTML = renderCoupangTable(rows);
  else $("tableWrap").innerHTML = renderCompareTable(rows);
}

async function analyzeCategory() {
  const path = currentPath();
  if (!path.length) {
    setStatus("1차 분류를 먼저 선택하세요.", "error");
    return;
  }
  state.selectedPath = path;
  const includedKeyword = $("includedKeyword").value.trim();
  const limit = Number($("keywordLimit").value || 12);
  setStatus(
    `${path.join(" > ")} 기준으로 키워드를 생성하고 조사 중입니다.\nChrome 수집 방식이면 별도 Chrome 창이 열릴 수 있습니다. 첫 실행에서 쿠팡 로그인이 필요하면 로그인 후 창을 유지하세요.`,
    "loading",
  );
  $("categoryAnalyzeBtn").disabled = true;
  try {
    const result = await api("/api/category-analysis", {
      method: "POST",
      body: JSON.stringify({ path, includedKeyword, limit }),
    });
    state.rows = result.rows || [];
    renderTable();
    setStatus(
      `${path.join(" > ")} · ${state.rows.length}개 키워드 조사가 완료되었습니다.\n쿠팡 수치는 각 행에 표시된 실제 수집 표본 범위 기준입니다.`,
      "success",
    );
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    $("categoryAnalyzeBtn").disabled = false;
  }
}

function summaryCard(label, value, sub = "") {
  return `<div class="summary-card"><div class="label">${escapeHtml(label)}</div><div class="value">${escapeHtml(value)}</div><div class="sub">${escapeHtml(sub)}</div></div>`;
}

function lineChart(searchPoints, clickPoints) {
  const allPeriods = Array.from(new Set([...(searchPoints || []).map((p) => p.period), ...(clickPoints || []).map((p) => p.period)])).sort();
  if (!allPeriods.length) return `<div class="warning-box">추이 데이터가 없습니다.</div>`;
  const width = 900;
  const height = 235;
  const padX = 42;
  const padY = 24;
  const usableW = width - padX * 2;
  const usableH = height - padY * 2;
  const map = (points) => new Map((points || []).map((p) => [p.period, Number(p.ratio)]));
  const searchMap = map(searchPoints);
  const clickMap = map(clickPoints);
  const x = (index) => padX + (allPeriods.length === 1 ? 0 : index / (allPeriods.length - 1)) * usableW;
  const y = (value) => padY + (1 - Math.max(0, Math.min(100, value)) / 100) * usableH;
  const pathFor = (valueMap) => allPeriods.map((period, index) => valueMap.has(period) ? `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(valueMap.get(period)).toFixed(1)}` : "").filter(Boolean).join(" ");
  const years = allPeriods.map((period, index) => ({ period, index })).filter((item, i) => i === 0 || item.period.slice(0, 4) !== allPeriods[i - 1].slice(0, 4));
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="네이버 상대 추이 그래프">
    ${[0,25,50,75,100].map((v) => `<line x1="${padX}" y1="${y(v)}" x2="${width-padX}" y2="${y(v)}" stroke="#e7ebef"/><text x="6" y="${y(v)+4}" font-size="10" fill="#778590">${v}</text>`).join("")}
    <path d="${pathFor(searchMap)}" fill="none" stroke="#3578e8" stroke-width="2.2"/>
    <path d="${pathFor(clickMap)}" fill="none" stroke="#00a83b" stroke-width="2.2"/>
    ${years.map((item) => `<text x="${x(item.index)}" y="${height-5}" font-size="10" fill="#778590">${escapeHtml(item.period.slice(0,4))}</text>`).join("")}
    <rect x="${width-250}" y="8" width="10" height="3" fill="#3578e8"/><text x="${width-235}" y="14" font-size="10">통합검색 상대지수</text>
    <rect x="${width-125}" y="8" width="10" height="3" fill="#00a83b"/><text x="${width-110}" y="14" font-size="10">쇼핑 클릭 상대지수</text>
  </svg>`;
}

function metricRow(label, value, note = "") {
  return `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(value)}${note ? `<span class="source-note">${escapeHtml(note)}</span>` : ""}</td></tr>`;
}

function productRows(products) {
  if (!products || !products.length) return `<tr><td colspan="5" class="muted">표시할 상품이 없습니다.</td></tr>`;
  return products.slice(0, 20).map((product, index) => `<tr>
    <td>${index + 1}</td>
    <td class="product-name"><a href="${escapeHtml(product.url || "#")}" target="_blank" rel="noreferrer">${escapeHtml(product.name || "상품")}</a></td>
    <td>${formatWon(product.price)}</td>
    <td>${formatNumber(product.review)}</td>
    <td>${escapeHtml({rocket:"로켓", sellerRocket:"판매자로켓", overseas:"해외", normal:"일반"}[product.delivery] || "-")}${product.ad ? " · 광고" : ""}</td>
  </tr>`).join("");
}

function renderDetail(data) {
  const naver = data.naver || {};
  const cp = get(data, "coupang.products", {});
  const np = naver.products || {};
  const searchTrend = naver.searchTrend || {};
  const clickTrend = naver.shoppingClickTrend || {};
  const exact = get(naver, "searchVolume.exact");
  const related = data.relatedKeywords || [];
  const frequencies = data.titleFrequency || [];
  const monthly = exact ? exact.monthlyTotalDisplay : "미설정";

  $("detailContent").innerHTML = `
    <div class="summary-grid">
      ${summaryCard("네이버 월 검색량", monthly, exact ? `PC ${exact.monthlyPcDisplay} · 모바일 ${exact.monthlyMobileDisplay}` : "검색광고 API 설정 시 표시")}
      ${summaryCard("통합검색 최근지수", formatNumber(searchTrend.latest), "네이버 상대지수")}
      ${summaryCard("쇼핑 클릭 최근지수", formatNumber(clickTrend.latest), "네이버 쇼핑 상대지수")}
      ${summaryCard("네이버 평균가", formatWon(get(np, "prices.avg")), np.sampleNotice || "공개 검색 표본")}
      ${summaryCard("쿠팡 평균가", formatWon(get(cp, "prices.avg")), cp.sampleNotice || "쿠팡 검색 표본")}
      ${summaryCard("쿠팡 총 리뷰", formatNumber(get(cp, "reviews.total"), "0"), `최대 ${formatNumber(get(cp, "reviews.max"))} · 평균 ${formatNumber(get(cp, "reviews.avg"))}`)}
    </div>

    <div class="warning-box">쿠팡 평균가·리뷰·배송비율은 <b>${formatNumber(cp.sampleCount, "0")}개 실제 수집 상품</b> 기준입니다. 쿠팡 전체 검색량이나 전체 클릭량으로 해석하면 안 됩니다.</div>

    <div class="detail-actions">
      <button class="secondary" id="openCoupangSearchBtn">쿠팡 검색결과 열기</button>
      <button class="secondary" id="openHtmlImportBtn">저장 HTML로 다시 계산</button>
      <button class="primary" id="refreshDetailBtn">현재 키워드 다시 조사</button>
    </div>

    <div class="detail-grid">
      <section class="detail-block">
        <h3>네이버 검색·쇼핑 클릭 추이</h3>
        <div class="content">${lineChart(searchTrend.points, clickTrend.points)}</div>
      </section>
      <section class="detail-block">
        <h3>쿠팡 시장 요약</h3>
        <div class="content"><table class="metric-table">
          ${metricRow("수집 상품 수", formatNumber(cp.sampleCount), cp.source || "")}
          ${metricRow("평균가", formatWon(get(cp, "prices.avg")))}
          ${metricRow("중앙가", formatWon(get(cp, "prices.median")))}
          ${metricRow("총 / 최대 / 평균 리뷰", `${formatNumber(get(cp, "reviews.total"), "0")} / ${formatNumber(get(cp, "reviews.max"))} / ${formatNumber(get(cp, "reviews.avg"))}`)}
          ${metricRow("로켓배송 비율", formatPercent(get(cp, "delivery.rocketRatio")))}
          ${metricRow("판매자로켓 비율", formatPercent(get(cp, "delivery.sellerRocketRatio")))}
          ${metricRow("일반배송 비율", formatPercent(get(cp, "delivery.normalRatio")))}
          ${metricRow("해외배송 비율", formatPercent(get(cp, "delivery.overseasRatio")))}
          ${metricRow("광고상품 비율", formatPercent(get(cp, "ads.ratio")))}
        </table></div>
      </section>
      <section class="detail-block">
        <h3>네이버 상품 요약</h3>
        <div class="content"><table class="metric-table">
          ${metricRow("검색 상품 수", formatNumber(np.reportedTotal), "네이버 페이지가 공개한 경우")}
          ${metricRow("실제 읽은 표본", formatNumber(np.sampleCount), np.source || "")}
          ${metricRow("최저 / 중앙 / 평균가", `${formatWon(get(np, "prices.min"))} / ${formatWon(get(np, "prices.median"))} / ${formatWon(get(np, "prices.avg"))}`)}
          ${metricRow("최근 3개월 검색 증감", formatPercent(searchTrend.change3m))}
          ${metricRow("최근 3개월 클릭 증감", formatPercent(clickTrend.change3m))}
          ${metricRow("최대 검색 시점", searchTrend.peakPeriod || "-")}
          ${metricRow("계절성", clickTrend.seasonality || searchTrend.seasonality || "-")}
        </table></div>
      </section>
      <section class="detail-block">
        <h3>연관·확장 키워드</h3>
        <div class="content">
          <div class="pill-row">${related.slice(0, 24).map((item) => `<button class="keyword-pill related-keyword" data-keyword="${encodeURIComponent(item.keyword)}">${escapeHtml(item.keyword)}${item.monthlyTotalDisplay ? ` · ${escapeHtml(item.monthlyTotalDisplay)}` : item.count ? ` · ${formatNumber(item.count)}` : ""}</button>`).join("") || `<span class="muted">연관 키워드가 없습니다.</span>`}</div>
          <h4>상품명 빈도</h4>
          <div class="pill-row">${frequencies.slice(0, 20).map((item) => `<span class="keyword-pill">${escapeHtml(item.keyword)} · ${formatNumber(item.count)}</span>`).join("") || `<span class="muted">상품명 표본이 부족합니다.</span>`}</div>
        </div>
      </section>
    </div>

    <section class="detail-block" style="margin-top:12px">
      <h3>쿠팡 검색 상위 상품 표본</h3>
      <div class="content" style="overflow:auto"><table class="product-table">
        <thead><tr><th>순위</th><th>상품명</th><th>가격</th><th>리뷰</th><th>배송</th></tr></thead>
        <tbody>${productRows(cp.products)}</tbody>
      </table></div>
    </section>`;

  $("openCoupangSearchBtn").addEventListener("click", () => window.open(cp.sourceUrl || `https://www.coupang.com/np/search?q=${encodeURIComponent(data.keyword)}`, "_blank"));
  $("openHtmlImportBtn").addEventListener("click", () => {
    $("htmlKeyword").value = data.keyword;
    openModal("htmlModal");
  });
  $("refreshDetailBtn").addEventListener("click", () => analyzeKeyword(data.keyword, data.categoryPath || [], data.categoryCode || ""));
  qsAll(".related-keyword", $("detailContent")).forEach((button) => button.addEventListener("click", () => {
    analyzeKeyword(decodeURIComponent(button.dataset.keyword), data.categoryPath || [], data.categoryCode || "");
  }));
}

async function analyzeKeyword(keyword, categoryPath = [], categoryCode = "") {
  state.currentDetail = { keyword, categoryPath, categoryCode };
  $("detailTitle").textContent = keyword;
  $("detailCategory").textContent = categoryPath.join(" > ");
  $("detailContent").innerHTML = "";
  setDetailStatus("네이버 추이와 네이버·쿠팡 상품 통계를 분석 중입니다. Chrome 수집 방식이면 별도 창이 열릴 수 있습니다.", "loading");
  openModal("detailModal");
  try {
    const data = await api("/api/keyword-analysis", {
      method: "POST",
      body: JSON.stringify({ keyword, categoryPath, categoryCode }),
    });
    state.currentDetail = data;
    renderDetail(data);
    setDetailStatus("분석이 완료되었습니다. 모든 쿠팡 통계는 화면에 표시된 표본 수 기준입니다.", "success");
  } catch (error) {
    setDetailStatus(error.message, "error");
  }
}

function settingsPayload() {
  return {
    naverApiHub: {
      clientId: $("naverClientId").value.trim(),
      clientSecret: $("naverClientSecret").value.trim(),
      defaultCategoryCode: $("naverCategoryCode").value.trim() || "50000000",
    },
    searchAd: {
      apiKey: $("searchAdApiKey").value.trim(),
      secretKey: $("searchAdSecret").value.trim(),
      customerId: $("searchAdCustomerId").value.trim(),
    },
    collector: {
      coupangMode: $("coupangMode").value,
      browserVisible: $("browserVisible").checked,
      sampleLimit: Number($("sampleLimit").value || 72),
    },
  };
}

function fillSettings(settings) {
  state.settings = settings;
  $("naverClientId").value = get(settings, "naverApiHub.clientId", "");
  $("naverClientSecret").value = "";
  $("naverCategoryCode").value = get(settings, "naverApiHub.defaultCategoryCode", "50000000");
  $("searchAdApiKey").value = get(settings, "searchAd.apiKey", "");
  $("searchAdSecret").value = "";
  $("searchAdCustomerId").value = get(settings, "searchAd.customerId", "");
  $("coupangMode").value = get(settings, "collector.coupangMode", "browser");
  $("browserVisible").checked = Boolean(get(settings, "collector.browserVisible", true));
  $("sampleLimit").value = get(settings, "collector.sampleLimit", 72);
}

async function loadSettings() {
  try {
    const settings = await api("/api/settings");
    fillSettings(settings);
    return settings;
  } catch (error) {
    setStatus(error.message, "error");
    return null;
  }
}

async function saveSettings(showMessage = true) {
  const settings = await api("/api/settings", { method: "POST", body: JSON.stringify(settingsPayload()) });
  fillSettings(settings);
  if (showMessage) $("connectionResult").textContent = "설정을 저장했습니다.";
  return settings;
}

async function testConnections() {
  $("connectionResult").textContent = "저장 후 연결 테스트 중...";
  try {
    const result = await api("/api/test-connections", { method: "POST", body: JSON.stringify(settingsPayload()) });
    fillSettings(result.settings);
    const labels = {
      searchTrend: "검색어 트렌드",
      shoppingInsight: "쇼핑 인사이트",
      searchAd: "네이버 검색광고 API",
      playwright: "Chrome 수집 모듈",
    };
    $("connectionResult").textContent = Object.entries(result.tests).map(([key, value]) => {
      const mark = value.ok === true ? "정상" : value.ok === false ? "실패" : "선택";
      return `${labels[key] || key}: ${mark} · ${value.message}`;
    }).join("\n");
  } catch (error) {
    $("connectionResult").textContent = `연결 테스트 실패: ${error.message}`;
  }
}

async function analyzePastedHtml() {
  const keyword = $("htmlKeyword").value.trim();
  const html = $("coupangHtml").value;
  if (!keyword || !html.trim()) return;
  $("analyzeHtmlBtn").disabled = true;
  try {
    const products = await api("/api/coupang-html-analysis", {
      method: "POST",
      body: JSON.stringify({ keyword, html }),
    });
    if (state.currentDetail && state.currentDetail.keyword === keyword) {
      state.currentDetail.coupang = state.currentDetail.coupang || {};
      state.currentDetail.coupang.products = products;
      renderDetail(state.currentDetail);
      setDetailStatus(`저장 HTML에서 ${products.sampleCount || 0}개 상품을 다시 계산했습니다.`, "success");
    }
    closeModal("htmlModal");
  } catch (error) {
    alert(error.message);
  } finally {
    $("analyzeHtmlBtn").disabled = false;
  }
}

function bindEvents() {
  $("categoryAnalyzeBtn").addEventListener("click", analyzeCategory);
  $("manualModeBtn").addEventListener("click", () => {
    const manual = $("manualSearch").classList.toggle("hidden");
    $("categorySearch").classList.toggle("hidden", !manual);
    $("manualModeBtn").classList.toggle("active", !manual);
  });
  $("manualAnalyzeBtn").addEventListener("click", () => {
    const keyword = $("manualKeyword").value.trim();
    if (keyword) analyzeKeyword(keyword, currentPath(), "");
  });
  $("manualKeyword").addEventListener("keydown", (event) => {
    if (event.key === "Enter") $("manualAnalyzeBtn").click();
  });

  qsAll(".tab").forEach((button) => button.addEventListener("click", () => {
    state.activeTab = button.dataset.tab;
    qsAll(".tab").forEach((item) => item.classList.toggle("active", item === button));
    renderTable();
  }));
  ["filterKeyword", "filterSearchMin", "filterCoupangPriceMax", "filterRocketMin", "filterReviewMax", "rowLimit"].forEach((id) => {
    $(id).addEventListener(id === "rowLimit" ? "change" : "input", renderTable);
  });

  $("tableWrap").addEventListener("click", (event) => {
    const button = event.target.closest(".keyword-link");
    if (!button) return;
    let path = [];
    try { path = JSON.parse(decodeURIComponent(button.dataset.category || "%5B%5D")); } catch { path = []; }
    analyzeKeyword(decodeURIComponent(button.dataset.keyword), path, button.dataset.code || "");
  });

  $("openSettingsBtn").addEventListener("click", async () => {
    await loadSettings();
    openModal("settingsModal");
  });
  $("refreshSettingsBtn").addEventListener("click", async () => {
    await loadSettings();
    openModal("settingsModal");
  });
  $("saveSettingsBtn").addEventListener("click", async () => {
    try { await saveSettings(true); } catch (error) { $("connectionResult").textContent = error.message; }
  });
  $("testConnectionsBtn").addEventListener("click", testConnections);
  $("analyzeHtmlBtn").addEventListener("click", analyzePastedHtml);

  qsAll("[data-close]").forEach((button) => button.addEventListener("click", () => closeModal(button.dataset.close)));
  qsAll(".modal-backdrop").forEach((backdrop) => backdrop.addEventListener("click", (event) => {
    if (event.target === backdrop) closeModal(backdrop.id);
  }));
}

async function initialize() {
  bindEvents();
  try {
    const [categories, settings] = await Promise.all([api("/api/categories"), api("/api/settings")]);
    state.categories = categories;
    initializeCategorySelectors();
    fillSettings(settings);
    const collectorStatus = settings.playwrightInstalled ? "Chrome 수집 모듈 설치됨" : "install.bat 실행 필요";
    setStatus(`준비 완료 · ${collectorStatus}`, settings.playwrightInstalled ? "success" : "info");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

initialize();
