const state = {
  categoryData: null,
  results: [],
  filtered: [],
  currentCategory: null,
  activeTab: 'naver',
  running: false,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  let payload;
  try { payload = await response.json(); }
  catch { payload = { error: `응답 해석 실패 (${response.status})` }; }
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function fmtNumber(value) {
  if (value === null || value === undefined || value === '') return '-';
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  return Math.round(number).toLocaleString('ko-KR');
}

function fmtPrice(value) {
  return value === null || value === undefined ? '-' : `${fmtNumber(value)}원`;
}

function fmtPercent(value, signed = false) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-';
  const n = Number(value);
  const prefix = signed && n > 0 ? '+' : '';
  return `${prefix}${n.toFixed(1)}%`;
}

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

function setStatus(message, type = '') {
  const line = $('#statusLine');
  line.textContent = message;
  line.className = `status-line ${type}`.trim();
}

function seasonalityLabel(value) {
  if (value === null || value === undefined) return { text: '-', className: '' };
  if (value < 25) return { text: '낮음', className: 'good' };
  if (value < 55) return { text: '중간', className: 'warn' };
  return { text: '높음', className: 'bad' };
}

function scorePill(value) {
  if (value === null || value === undefined) return '<span class="pill">-</span>';
  const cls = value < 45 ? 'good' : value < 70 ? 'warn' : 'bad';
  return `<span class="pill ${cls}">${Number(value).toFixed(1)}</span>`;
}

function growthCell(value) {
  if (value === null || value === undefined) return '<span class="muted">-</span>';
  const cls = value > 0 ? 'positive' : value < 0 ? 'negative' : '';
  return `<span class="${cls}">${fmtPercent(value, true)}</span>`;
}

function errorCell(message) {
  return `<span class="error-text" title="${esc(message)}">오류: ${esc(message)}</span>`;
}

function getSelectNode(select) {
  const idx = select.selectedIndex - 1;
  return idx >= 0 && select._nodes ? select._nodes[idx] : null;
}

function populateSelect(select, nodes, placeholder) {
  select._nodes = nodes || [];
  select.innerHTML = `<option value="">${placeholder}</option>` + (nodes || []).map((node, index) =>
    `<option value="${esc(node.code)}" data-index="${index}">${esc(node.name)}</option>`
  ).join('');
  select.disabled = !(nodes && nodes.length);
}

function resetFollowing(level) {
  for (let n = level + 1; n <= 4; n += 1) {
    populateSelect($(`#category${n}`), [], `${n}차 분류`);
  }
}

function categoryChanged(level) {
  const select = $(`#category${level}`);
  const node = getSelectNode(select);
  resetFollowing(level);
  if (node?.children?.length && level < 4) {
    populateSelect($(`#category${level + 1}`), node.children, `${level + 1}차 분류`);
  }
}

function selectedCategoryPath() {
  const pathCodes = [];
  const pathNames = [];
  let lastNode = null;
  for (let level = 1; level <= 4; level += 1) {
    const select = $(`#category${level}`);
    const node = getSelectNode(select);
    if (!node) break;
    pathCodes.push(String(node.code));
    pathNames.push(node.name);
    lastNode = node;
  }
  return { pathCodes, pathNames, lastNode };
}

async function loadCategories() {
  state.categoryData = await api('/api/categories');
  populateSelect($('#category1'), state.categoryData.categories || [], '1차 분류');
  for (let level = 2; level <= 4; level += 1) populateSelect($(`#category${level}`), [], `${level}차 분류`);
}

function makeEmptyRows(message = '카테고리를 선택하면 분석 결과가 여기에 표시됩니다.') {
  ['#naverTable tbody', '#coupangTable tbody', '#combinedTable tbody'].forEach(selector => {
    const tbody = $(selector);
    const columns = selector.includes('naver') ? 16 : selector.includes('coupang') ? 19 : 13;
    tbody.innerHTML = `<tr class="empty-row"><td colspan="${columns}">${esc(message)}</td></tr>`;
  });
}

function addProgress(done, total) {
  let bar = $('.progress-bar');
  if (!bar) {
    bar = document.createElement('div');
    bar.className = 'progress-bar';
    bar.innerHTML = '<span></span>';
    $('#statusLine').insertAdjacentElement('afterend', bar);
  }
  bar.querySelector('span').style.width = `${total ? (done / total * 100) : 0}%`;
  if (done >= total) setTimeout(() => bar.remove(), 900);
}

async function runCategorySearch() {
  if (state.running) return;
  const selected = selectedCategoryPath();
  if (!selected.lastNode) {
    setStatus('1차 분류부터 선택하세요.', 'error');
    return;
  }
  if (selected.lastNode.children?.length) {
    setStatus('마지막 세부 분류까지 선택하세요.', 'error');
    return;
  }
  state.running = true;
  $('#runCategorySearch').disabled = true;
  state.results = [];
  state.filtered = [];
  renderAll();
  setStatus('선택한 카테고리에서 키워드 후보를 찾는 중입니다…', 'loading');
  try {
    const discovery = await api('/api/discover', {
      method: 'POST', body: JSON.stringify({ pathCodes: selected.pathCodes, pathNames: selected.pathNames }),
    });
    state.currentCategory = discovery.category;
    const keywords = discovery.keywords || [];
    if (!keywords.length) throw new Error('발견된 키워드가 없습니다.');
    setStatus(`${discovery.category.pathNames.join(' > ')}: ${keywords.length}개 키워드를 네이버·쿠팡에서 조사합니다.`, 'loading');
    if (discovery.warnings?.length) console.warn('키워드 발굴 경고', discovery.warnings);
    await analyzeKeywordQueue(keywords, discovery.category.naverCategoryCode || '');
    setStatus(`조사 완료: ${state.results.length}개 키워드`, 'success');
  } catch (error) {
    setStatus(error.message, 'error');
    if (!state.results.length) makeEmptyRows(error.message);
  } finally {
    state.running = false;
    $('#runCategorySearch').disabled = false;
  }
}

async function analyzeKeywordQueue(keywords, categoryCode) {
  let cursor = 0;
  let done = 0;
  const workerCount = Math.min(2, keywords.length);
  addProgress(0, keywords.length);
  async function worker() {
    while (cursor < keywords.length) {
      const index = cursor++;
      const keyword = keywords[index];
      try {
        const result = await api('/api/analyze-keyword', {
          method: 'POST', body: JSON.stringify({ keyword, categoryCode }),
        });
        result.categoryPath = state.currentCategory?.pathNames?.join(' > ') || '';
        result.order = index;
        state.results.push(result);
      } catch (error) {
        state.results.push({
          keyword, order: index, categoryPath: state.currentCategory?.pathNames?.join(' > ') || '',
          trend: { status: 'error', error: error.message },
          naver: { status: 'error', error: error.message },
          coupang: { status: 'error', error: error.message },
          errors: { request: error.message },
        });
      }
      done += 1;
      state.results.sort((a, b) => a.order - b.order);
      applyFilters(false);
      addProgress(done, keywords.length);
      setStatus(`${done}/${keywords.length} 분석 완료 — 표가 순서대로 채워지고 있습니다.`, 'loading');
    }
  }
  await Promise.all(Array.from({ length: workerCount }, worker));
}

async function runDirectKeyword() {
  if (state.running) return;
  const keyword = $('#directKeyword').value.trim();
  if (!keyword) return setStatus('조사할 키워드를 입력하세요.', 'error');
  state.running = true;
  state.currentCategory = { pathNames: ['직접 조사'], naverCategoryCode: $('#directCategoryCode').value.trim() };
  state.results = [];
  renderAll();
  setStatus(`${keyword} 조사 중…`, 'loading');
  try {
    const result = await api('/api/analyze-keyword', {
      method: 'POST', body: JSON.stringify({ keyword, categoryCode: $('#directCategoryCode').value.trim() }),
    });
    result.categoryPath = '직접 조사'; result.order = 0;
    state.results.push(result);
    applyFilters(false);
    setStatus(`${keyword} 조사 완료`, 'success');
  } catch (error) { setStatus(error.message, 'error'); }
  finally { state.running = false; }
}

function valueInRange(value, minValue, maxValue) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return !minValue && !maxValue;
  const n = Number(value);
  if (minValue !== '' && n < Number(minValue)) return false;
  if (maxValue !== '' && n > Number(maxValue)) return false;
  return true;
}

function activePlatformData(result) {
  return state.activeTab === 'coupang' ? result.coupang : result.naver;
}

function applyFilters(updateStatus = true) {
  const keywordNeedle = $('#filterKeyword').value.trim().toLowerCase();
  const compMin = $('#filterCompetitionMin').value;
  const compMax = $('#filterCompetitionMax').value;
  const growthMin = $('#filterGrowthMin').value;
  const growthMax = $('#filterGrowthMax').value;
  const priceMin = $('#filterPriceMin').value;
  const priceMax = $('#filterPriceMax').value;
  const sampleMin = $('#filterSampleMin').value;
  const sampleMax = $('#filterSampleMax').value;
  const seasonality = $('#filterSeasonality').value;
  const status = $('#filterStatus').value;

  state.filtered = state.results.filter(result => {
    const platform = activePlatformData(result) || {};
    const trend = result.trend || {};
    if (keywordNeedle && !result.keyword.toLowerCase().includes(keywordNeedle)) return false;
    if (!valueInRange(platform.competitionScore, compMin, compMax)) return false;
    if (!valueInRange(trend.growth3, growthMin, growthMax)) return false;
    if (!valueInRange(platform.prices?.median, priceMin, priceMax)) return false;
    if (!valueInRange(platform.sampleCount, sampleMin, sampleMax)) return false;
    if (seasonality !== 'all') {
      const v = trend.seasonality;
      const group = v === null || v === undefined ? 'unknown' : v < 25 ? 'low' : v < 55 ? 'mid' : 'high';
      if (group !== seasonality) return false;
    }
    if (status === 'ok' && (platform.status !== 'ok' || trend.status !== 'ok')) return false;
    if (status === 'error' && platform.status !== 'error' && trend.status !== 'error') return false;
    return true;
  });
  renderAll();
  if (updateStatus) setStatus(`필터 결과 ${state.filtered.length}/${state.results.length}개`, 'success');
}

function trendCells(result) {
  const trend = result.trend || {};
  if (trend.status === 'error') {
    return `<td colspan="6">${errorCell(trend.error || '트렌드 조회 실패')}</td>`;
  }
  const season = seasonalityLabel(trend.seasonality);
  return `
    <td class="number">${fmtNumber(trend.recent1)}</td>
    <td class="number">${fmtNumber(trend.recent3)}</td>
    <td>${growthCell(trend.growth3)}</td>
    <td>${growthCell(trend.yoy)}</td>
    <td><span class="pill ${season.className}">${season.text}</span></td>
    <td>${esc(trend.peakPeriod || '-')}</td>`;
}

function renderNaverRow(result) {
  const data = result.naver || {};
  const base = `<td class="keyword-cell" title="${esc(result.keyword)}">${esc(result.keyword)}</td><td class="category-cell" title="${esc(result.categoryPath)}">${esc(result.categoryPath)}</td>${trendCells(result)}`;
  if (data.status === 'error') return `<tr>${base}<td colspan="8">${errorCell(data.error || '네이버 조회 실패')}</td></tr>`;
  return `<tr>${base}
    <td class="number">${fmtNumber(data.total)}</td>
    <td class="number">${fmtNumber(data.sampleCount)}</td>
    <td class="number">${fmtPrice(data.prices?.min)}</td>
    <td class="number">${fmtPrice(data.prices?.median)}</td>
    <td class="number">${fmtPrice(data.prices?.average)}</td>
    <td class="number">${fmtNumber(data.overseasCount)}</td>
    <td class="number">${fmtNumber(data.mallCount)}</td>
    <td>${scorePill(data.competitionScore)}</td>
  </tr>`;
}

function renderCoupangRow(result) {
  const data = result.coupang || {};
  const base = `<td class="keyword-cell" title="${esc(result.keyword)}">${esc(result.keyword)}</td><td class="category-cell" title="${esc(result.categoryPath)}">${esc(result.categoryPath)}</td>${trendCells(result)}`;
  if (data.status === 'error') return `<tr>${base}<td colspan="11">${errorCell(data.error || '쿠팡 조회 실패')}</td></tr>`;
  return `<tr>${base}
    <td class="number">${data.total ? fmtNumber(data.total) : '<span class="muted">미공개</span>'}</td>
    <td class="number">${fmtNumber(data.sampleCount)}</td>
    <td class="number">${fmtPrice(data.prices?.min)}</td>
    <td class="number">${fmtPrice(data.prices?.median)}</td>
    <td class="number">${fmtPrice(data.prices?.average)}</td>
    <td class="number">${fmtNumber(data.reviews?.max)}</td>
    <td class="number">${fmtNumber(data.reviews?.average)}</td>
    <td class="number">${fmtNumber(data.rocketCount)}</td>
    <td class="number">${fmtNumber(data.rocketGrowthCount)}</td>
    <td class="number">${fmtNumber(data.adCount)}</td>
    <td>${scorePill(data.competitionScore)}</td>
  </tr>`;
}

function combinedDecision(result) {
  const n = result.naver || {};
  const c = result.coupang || {};
  const growth = result.trend?.growth3;
  if (n.status === 'error' || c.status === 'error') return { text: '수동 확인', cls: 'watch' };
  const averageCompetition = [n.competitionScore, c.competitionScore].filter(v => Number.isFinite(Number(v)));
  const comp = averageCompetition.length ? averageCompetition.reduce((a,b) => a + Number(b), 0) / averageCompetition.length : 50;
  if (growth > 10 && comp < 60) return { text: '우선 검토', cls: 'review' };
  if (comp >= 78) return { text: '경쟁 과열', cls: 'avoid' };
  if (growth < -15) return { text: '수요 하락', cls: 'avoid' };
  return { text: '추가 검증', cls: 'watch' };
}

function renderCombinedRow(result) {
  const n = result.naver || {};
  const c = result.coupang || {};
  const nSample = Math.max(1, Number(n.sampleCount || 0));
  const cSample = Math.max(1, Number(c.sampleCount || 0));
  const overseasRatio = n.status === 'ok' ? n.overseasCount / nSample * 100 : null;
  const rocketRatio = c.status === 'ok' ? c.rocketCount / cSample * 100 : null;
  const priceGap = Number.isFinite(Number(n.prices?.median)) && Number.isFinite(Number(c.prices?.median))
    ? Number(c.prices.median) - Number(n.prices.median) : null;
  const decision = combinedDecision(result);
  return `<tr>
    <td class="keyword-cell">${esc(result.keyword)}</td><td class="category-cell">${esc(result.categoryPath)}</td>
    <td>${n.status === 'ok' ? fmtNumber(n.total) : '-'}</td><td>${n.status === 'ok' ? fmtPrice(n.prices?.median) : '-'}</td><td>${fmtPercent(overseasRatio)}</td><td>${scorePill(n.competitionScore)}</td>
    <td>${c.status === 'ok' ? fmtNumber(c.sampleCount) : '-'}</td><td>${c.status === 'ok' ? fmtPrice(c.prices?.median) : '-'}</td><td>${fmtPercent(rocketRatio)}</td><td>${scorePill(c.competitionScore)}</td>
    <td class="number">${priceGap === null ? '-' : `${priceGap > 0 ? '+' : ''}${fmtPrice(priceGap)}`}</td><td>${growthCell(result.trend?.growth3)}</td><td><span class="decision ${decision.cls}">${decision.text}</span></td>
  </tr>`;
}

function renderAll() {
  const rows = state.filtered.length || state.results.length === 0 ? state.filtered : state.results;
  const useRows = state.results.length && state.filtered.length === 0 && hasActiveFilters() ? [] : (state.filtered.length ? state.filtered : state.results);
  const tables = [
    ['#naverTable tbody', 16, renderNaverRow],
    ['#coupangTable tbody', 19, renderCoupangRow],
    ['#combinedTable tbody', 13, renderCombinedRow],
  ];
  for (const [selector, columns, renderer] of tables) {
    const tbody = $(selector);
    if (!state.results.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="${columns}">카테고리를 선택하면 분석 결과가 여기에 표시됩니다.</td></tr>`;
    } else if (!useRows.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="${columns}">필터 조건에 맞는 결과가 없습니다.</td></tr>`;
    } else {
      tbody.innerHTML = useRows.map(renderer).join('');
    }
  }
  $('#resultSummary').textContent = state.results.length ? `표시 ${useRows.length}개 / 조사 ${state.results.length}개` : '조사 전';
}

function hasActiveFilters() {
  return ['filterKeyword','filterCompetitionMin','filterCompetitionMax','filterGrowthMin','filterGrowthMax','filterPriceMin','filterPriceMax','filterSampleMin','filterSampleMax']
    .some(id => $(`#${id}`).value !== '') || $('#filterSeasonality').value !== 'all' || $('#filterStatus').value !== 'all';
}

function resetFilters() {
  ['filterKeyword','filterCompetitionMin','filterCompetitionMax','filterGrowthMin','filterGrowthMax','filterPriceMin','filterPriceMax','filterSampleMin','filterSampleMax'].forEach(id => $(`#${id}`).value = '');
  $('#filterSeasonality').value = 'all'; $('#filterStatus').value = 'all';
  state.filtered = [...state.results]; renderAll();
}

function switchTab(tab) {
  state.activeTab = tab;
  $$('.view-tabs button').forEach(button => button.classList.toggle('active', button.dataset.tab === tab));
  ['naver','coupang','combined'].forEach(name => $(`#${name}Tab`).classList.toggle('active', name === tab));
  applyFilters(false);
}

function switchMode(direct) {
  $('.mode-tabs button:first-child').classList.toggle('active', !direct);
  $('#keywordModeButton').classList.toggle('active', direct);
  $('#categorySearchRow').classList.toggle('hidden', direct);
  $('#keywordSearchRow').classList.toggle('hidden', !direct);
}

function csvEscape(value) {
  const text = String(value ?? '');
  return `"${text.replaceAll('"', '""')}"`;
}

function exportCsv() {
  const data = state.filtered.length ? state.filtered : state.results;
  if (!data.length) return setStatus('저장할 결과가 없습니다.', 'error');
  let headers, rows;
  if (state.activeTab === 'coupang') {
    headers = ['키워드','카테고리','최근지수','3개월증감률','검색결과수','표본','최저가','중앙가','평균가','최대리뷰','평균리뷰','로켓','로켓그로스','광고','경쟁도','오류'];
    rows = data.map(r => [r.keyword,r.categoryPath,r.trend?.recent1,r.trend?.growth3,r.coupang?.total,r.coupang?.sampleCount,r.coupang?.prices?.min,r.coupang?.prices?.median,r.coupang?.prices?.average,r.coupang?.reviews?.max,r.coupang?.reviews?.average,r.coupang?.rocketCount,r.coupang?.rocketGrowthCount,r.coupang?.adCount,r.coupang?.competitionScore,r.coupang?.error]);
  } else if (state.activeTab === 'combined') {
    headers = ['키워드','카테고리','3개월증감률','네이버상품수','네이버중앙가','네이버경쟁도','쿠팡표본','쿠팡중앙가','쿠팡경쟁도','판정'];
    rows = data.map(r => [r.keyword,r.categoryPath,r.trend?.growth3,r.naver?.total,r.naver?.prices?.median,r.naver?.competitionScore,r.coupang?.sampleCount,r.coupang?.prices?.median,r.coupang?.competitionScore,combinedDecision(r).text]);
  } else {
    headers = ['키워드','카테고리','최근지수','3개월증감률','전년비','계절성','상품수','표본','최저가','중앙가','평균가','해외배송','몰수','경쟁도','오류'];
    rows = data.map(r => [r.keyword,r.categoryPath,r.trend?.recent1,r.trend?.growth3,r.trend?.yoy,r.trend?.seasonality,r.naver?.total,r.naver?.sampleCount,r.naver?.prices?.min,r.naver?.prices?.median,r.naver?.prices?.average,r.naver?.overseasCount,r.naver?.mallCount,r.naver?.competitionScore,r.naver?.error]);
  }
  const csv = '\ufeff' + [headers, ...rows].map(row => row.map(csvEscape).join(',')).join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = `seller-gap-${state.activeTab}-${new Date().toISOString().slice(0,10)}.csv`;
  anchor.click(); URL.revokeObjectURL(url);
}

async function openApiModal() {
  $('#apiModal').classList.remove('hidden');
  $('#apiTestResult').textContent = '설정을 불러오는 중…';
  try {
    const config = await api('/api/config');
    $('#clientId').value = config.naverApiHub?.clientId || '';
    $('#clientSecret').value = config.naverApiHub?.clientSecret || '';
    $('#apiTestResult').textContent = config.naverApiHub?.configured ? '저장된 API 키가 있습니다.' : 'API 키를 입력하세요.';
  } catch (error) { $('#apiTestResult').textContent = error.message; }
}

async function saveApiSettings(showMessage = true) {
  await api('/api/config', {
    method: 'POST', body: JSON.stringify({ naverApiHub: { clientId: $('#clientId').value.trim(), clientSecret: $('#clientSecret').value.trim() } }),
  });
  if (showMessage) $('#apiTestResult').textContent = '설정을 저장했습니다.';
}

async function testApiSettings() {
  $('#apiTestResult').textContent = '저장 후 검색어 트렌드와 쇼핑 검색 권한을 확인하는 중…';
  try {
    await saveApiSettings(false);
    const result = await api('/api/config/test', { method: 'POST', body: '{}' });
    const trend = result.checks?.searchTrend;
    const shop = result.checks?.shoppingSearch;
    $('#apiTestResult').textContent = [
      `검색어 트렌드: ${trend?.ok ? '정상' : `실패 — ${trend?.error || '알 수 없음'}`}`,
      `쇼핑 검색: ${shop?.ok ? `정상 (표본 ${shop.sample || 0}개)` : `실패 — ${shop?.error || '알 수 없음'}`}`,
      result.ok ? '필요한 핵심 연결이 모두 확인됐습니다.' : 'NAVER API HUB Application에서 실패한 API 권한을 추가하세요.'
    ].join('\n');
  } catch (error) { $('#apiTestResult').textContent = error.message; }
}

function bindEvents() {
  for (let level = 1; level <= 4; level += 1) $(`#category${level}`).addEventListener('change', () => categoryChanged(level));
  $('#runCategorySearch').addEventListener('click', runCategorySearch);
  $('#runKeywordSearch').addEventListener('click', runDirectKeyword);
  $('#directKeyword').addEventListener('keydown', event => { if (event.key === 'Enter') runDirectKeyword(); });
  $('.mode-tabs button:first-child').addEventListener('click', () => switchMode(false));
  $('#keywordModeButton').addEventListener('click', () => switchMode(true));
  $$('.view-tabs button').forEach(button => button.addEventListener('click', () => switchTab(button.dataset.tab)));
  $('#applyFilters').addEventListener('click', () => applyFilters(true));
  $('#resetFilters').addEventListener('click', resetFilters);
  $('#exportCsv').addEventListener('click', exportCsv);
  $('#openApiSettings').addEventListener('click', openApiModal);
  $('#closeApiModal').addEventListener('click', () => $('#apiModal').classList.add('hidden'));
  $('#apiModal').addEventListener('click', event => { if (event.target.id === 'apiModal') $('#apiModal').classList.add('hidden'); });
  $('#saveApiSettings').addEventListener('click', () => saveApiSettings(true).catch(error => $('#apiTestResult').textContent = error.message));
  $('#testApiSettings').addEventListener('click', testApiSettings);
}

async function init() {
  bindEvents();
  makeEmptyRows();
  try {
    await loadCategories();
    setStatus('1차부터 마지막 분류까지 선택하고 돋보기를 누르세요. 네이버와 쿠팡 결과가 순차적으로 채워집니다.');
  } catch (error) { setStatus(`초기화 실패: ${error.message}`, 'error'); }
}

init();
