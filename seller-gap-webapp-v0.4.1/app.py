from __future__ import annotations

import json
import re
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CONFIG_FILE = DATA_DIR / "config.json"
HOST = "127.0.0.1"
PORT = 8000
API_BASE = "https://naverapihub.apigw.ntruss.com"

DEFAULT_CONFIG = {
    "clientId": "",
    "clientSecret": "",
    "categoryCode": "50000000",
}

TOP_CATEGORY_CODES = {
    "패션의류": "50000000",
    "패션잡화": "50000001",
    "화장품/미용": "50000002",
    "디지털/가전": "50000003",
    "가구/인테리어": "50000004",
    "출산/육아": "50000005",
    "식품": "50000006",
    "스포츠/레저": "50000007",
    "생활/건강": "50000008",
    "여가/생활편의": "50000009",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)


def ensure_data() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> dict[str, str]:
    ensure_data()
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    return {**DEFAULT_CONFIG, **saved}


def save_config(new_config: dict[str, Any]) -> dict[str, str]:
    current = load_config()
    client_secret = str(new_config.get("clientSecret", "")).strip()
    merged = {
        "clientId": str(new_config.get("clientId", current["clientId"])).strip(),
        "clientSecret": client_secret if client_secret else current["clientSecret"],
        "categoryCode": str(new_config.get("categoryCode", current["categoryCode"])).strip()
        or "50000000",
    }
    CONFIG_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
) -> dict[str, Any]:
    body = None
    request_headers = headers.copy() if headers else {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return json.loads(text)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"연결 실패: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("API 응답이 JSON 형식이 아닙니다.") from exc


def naver_headers(config: dict[str, str]) -> dict[str, str]:
    if not config.get("clientId") or not config.get("clientSecret"):
        raise RuntimeError("NAVER API HUB Client ID와 Client Secret을 먼저 저장하세요.")
    return {
        "X-NCP-APIGW-API-KEY-ID": config["clientId"],
        "X-NCP-APIGW-API-KEY": config["clientSecret"],
        "Content-Type": "application/json",
    }


def date_range() -> tuple[str, str]:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=730)
    return start.isoformat(), end.isoformat()


def summarize_trend(data: list[dict[str, Any]]) -> dict[str, Any]:
    points = []
    for item in data:
        try:
            points.append({"period": str(item.get("period", "")), "ratio": float(item.get("ratio", 0))})
        except (TypeError, ValueError):
            continue
    ratios = [p["ratio"] for p in points]
    if not ratios:
        return {"available": False, "points": []}
    latest = ratios[-1]
    recent = ratios[-3:]
    previous = ratios[-6:-3]
    recent_avg = sum(recent) / len(recent)
    previous_avg = sum(previous) / len(previous) if previous else 0
    change_3m = ((recent_avg - previous_avg) / previous_avg * 100) if previous_avg else None
    yoy = None
    if len(ratios) >= 13 and ratios[-13] != 0:
        yoy = (latest - ratios[-13]) / ratios[-13] * 100
    peak_index = max(range(len(ratios)), key=ratios.__getitem__)
    return {
        "available": True,
        "latest": round(latest, 2),
        "recent3Avg": round(recent_avg, 2),
        "change3m": round(change_3m, 2) if change_3m is not None else None,
        "yoy": round(yoy, 2) if yoy is not None else None,
        "peakPeriod": points[peak_index]["period"],
        "points": points,
    }


def search_trend(keyword: str, config: dict[str, str]) -> dict[str, Any]:
    start, end = date_range()
    payload = {
        "startDate": start,
        "endDate": end,
        "timeUnit": "month",
        "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}],
    }
    response = json_request(
        f"{API_BASE}/search-trend/v1/search",
        method="POST",
        payload=payload,
        headers=naver_headers(config),
    )
    results = response.get("results") or []
    if not results:
        return {"available": False, "error": "검색어 트렌드 결과가 없습니다."}
    return summarize_trend(results[0].get("data") or [])


def shopping_click_trend(keyword: str, category_code: str, config: dict[str, str]) -> dict[str, Any]:
    start, end = date_range()
    payload = {
        "startDate": start,
        "endDate": end,
        "timeUnit": "month",
        "category": category_code,
        "keyword": [{"name": keyword, "param": [keyword]}],
    }
    response = json_request(
        f"{API_BASE}/shopping/v1/category/keywords",
        method="POST",
        payload=payload,
        headers=naver_headers(config),
    )
    results = response.get("results") or []
    if not results:
        return {"available": False, "error": "쇼핑 클릭 추이 결과가 없습니다."}
    return summarize_trend(results[0].get("data") or [])


def clean_number(value: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", value or "")
    if not digits:
        return None
    number = int(digits)
    return number if number > 0 else None


def price_summary(values: list[int]) -> dict[str, Any]:
    normalized = [v for v in values if 100 <= v <= 100_000_000]
    if not normalized:
        return {"count": 0, "min": None, "median": None, "avg": None}
    normalized = normalized[:200]
    return {
        "count": len(normalized),
        "min": min(normalized),
        "median": int(statistics.median(normalized)),
        "avg": int(sum(normalized) / len(normalized)),
    }


def fetch_html(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"공개 검색화면 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"공개 검색화면 연결 실패: {exc.reason}") from exc


def naver_public_products(keyword: str) -> dict[str, Any]:
    url = "https://search.shopping.naver.com/ns/search?" + urllib.parse.urlencode({"query": keyword})
    try:
        text = fetch_html(url)
    except RuntimeError as exc:
        return {"available": False, "error": str(exc), "url": url}

    price_patterns = [
        r'"lowPrice"\s*:\s*"?(\d{3,})',
        r'"price"\s*:\s*"?(\d{3,})',
        r'"salePrice"\s*:\s*"?(\d{3,})',
        r'([0-9][0-9,]{2,})\s*원',
    ]
    prices: list[int] = []
    for pattern in price_patterns:
        for raw in re.findall(pattern, text, flags=re.IGNORECASE):
            number = clean_number(raw)
            if number is not None:
                prices.append(number)
        if len(prices) >= 10:
            break

    titles = []
    for pattern in [r'"productTitle"\s*:\s*"([^"]{2,160})"', r'"productName"\s*:\s*"([^"]{2,160})"']:
        titles.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    titles = list(dict.fromkeys(titles))[:100]

    total = None
    for pattern in [r'"total"\s*:\s*(\d+)', r'"totalCount"\s*:\s*(\d+)']:
        match = re.search(pattern, text)
        if match:
            total = int(match.group(1))
            break

    return {
        "available": bool(prices or titles or total),
        "url": url,
        "sampleProducts": len(titles) or price_summary(prices)["count"],
        "total": total,
        "prices": price_summary(prices),
        "status": "공개 검색화면 표본",
        "error": None if (prices or titles or total) else "페이지는 열렸지만 상품 데이터를 찾지 못했습니다.",
    }


def coupang_public_products(keyword: str) -> dict[str, Any]:
    url = "https://www.coupang.com/np/search?" + urllib.parse.urlencode({"q": keyword})
    try:
        text = fetch_html(url)
    except RuntimeError as exc:
        return {"available": False, "error": str(exc), "url": url}

    prices: list[int] = []
    for pattern in [
        r'class="price-value"[^>]*>\s*([0-9,]+)',
        r'"salePrice"\s*:\s*(\d+)',
        r'"price"\s*:\s*(\d+)',
    ]:
        for raw in re.findall(pattern, text, flags=re.IGNORECASE):
            number = clean_number(raw)
            if number is not None:
                prices.append(number)
        if len(prices) >= 10:
            break

    reviews: list[int] = []
    for pattern in [
        r'rating-total-count[^>]*>\s*\(?([0-9,]+)\)?',
        r'"ratingCount"\s*:\s*(\d+)',
        r'"reviewCount"\s*:\s*(\d+)',
    ]:
        for raw in re.findall(pattern, text, flags=re.IGNORECASE):
            number = clean_number(raw)
            if number is not None:
                reviews.append(number)
        if reviews:
            break

    titles = re.findall(r'class="name"[^>]*>\s*([^<]{2,160})<', text, flags=re.IGNORECASE)
    titles = list(dict.fromkeys(t.strip() for t in titles if t.strip()))[:100]
    rocket_count = len(re.findall(r'로켓배송|rocket[_-]?(?:logo|delivery)', text, flags=re.IGNORECASE))
    ad_count = len(re.findall(r'>\s*광고\s*<|ad-badge|isAd', text, flags=re.IGNORECASE))
    review_summary = {
        "count": len(reviews),
        "max": max(reviews) if reviews else None,
        "avg": int(sum(reviews) / len(reviews)) if reviews else None,
    }
    return {
        "available": bool(prices or titles or reviews),
        "url": url,
        "sampleProducts": len(titles) or price_summary(prices)["count"],
        "prices": price_summary(prices),
        "reviews": review_summary,
        "rocketCount": rocket_count,
        "adCount": ad_count,
        "status": "공개 검색화면 표본",
        "error": None if (prices or titles or reviews) else "페이지는 열렸지만 상품 데이터를 찾지 못했습니다.",
        "trend": {
            "available": False,
            "reason": "쿠팡은 경쟁상품 검색량·클릭 추이 공개 API를 제공하지 않습니다.",
        },
    }


def analyze_keyword(keyword: str, category_code: str, config: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "keyword": keyword,
        "naver": {},
        "coupang": {},
    }
    try:
        result["naver"]["searchTrend"] = search_trend(keyword, config)
    except RuntimeError as exc:
        result["naver"]["searchTrend"] = {"available": False, "error": str(exc)}
    try:
        result["naver"]["shoppingClickTrend"] = shopping_click_trend(keyword, category_code, config)
    except RuntimeError as exc:
        result["naver"]["shoppingClickTrend"] = {"available": False, "error": str(exc)}
    result["naver"]["products"] = naver_public_products(keyword)
    result["coupang"]["products"] = coupang_public_products(keyword)
    return result


def test_apis(config: dict[str, str], category_code: str) -> dict[str, Any]:
    tests: dict[str, Any] = {}
    try:
        value = search_trend("테스트", config)
        tests["searchTrend"] = {"ok": bool(value.get("available")), "message": "정상"}
    except RuntimeError as exc:
        tests["searchTrend"] = {"ok": False, "message": str(exc)}
    try:
        value = shopping_click_trend("테스트", category_code, config)
        tests["shoppingInsight"] = {"ok": bool(value.get("available")), "message": "정상"}
    except RuntimeError as exc:
        tests["shoppingInsight"] = {"ok": False, "message": str(exc)}
    return tests


HTML = r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>셀러 갭 소싱 v0.4.1</title>
<style>
:root{--navy:#263d50;--blue:#2f72e8;--green:#00ba2f;--red:#ed3348;--line:#dbe2ea;--soft:#f5f7fa;--text:#1c2733}
*{box-sizing:border-box}body{margin:0;font-family:Arial,"Noto Sans KR",sans-serif;color:var(--text);background:#fff;font-size:13px}
header{height:48px;border-bottom:1px solid #e5e8ec;display:flex;align-items:center;justify-content:space-between;padding:0 22px}.brand{font-weight:800;font-size:17px}.brand span{color:#8995a1;font-weight:600;margin-left:16px}.head-actions button{border:0;background:#26313b;color:white;border-radius:16px;padding:8px 14px;cursor:pointer}
.hero{text-align:center;padding:30px 28px 18px}.hero h1{font-size:30px;margin:0 0 28px;background:linear-gradient(90deg,#7449d8,#00a9d5);color:transparent;background-clip:text}.category-bar{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr)) 52px;gap:8px;max-width:920px;margin:auto;padding:10px;background:#f5f6fa;border-radius:12px}.category-bar select,.category-bar input{height:42px;border:1px solid #e1e5eb;border-radius:6px;background:white;padding:0 12px}.search-btn{border:0;border-radius:7px;background:var(--blue);color:#fff;font-size:24px;cursor:pointer}.helper{margin-top:10px;color:#61707d}.helper strong{color:#b51d37}
main{padding:0 26px 32px}.status{margin:0 auto 12px;max-width:1600px;padding:10px 12px;background:#f1f5fb;border:1px solid #dbe5f3;border-radius:6px;min-height:38px}.filters{max-width:1600px;margin:auto;border:1px solid var(--line);background:var(--soft)}.filter-head{background:var(--navy);color:white;padding:9px 12px;font-weight:700}.filter-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line)}.filter-box{background:#fff;padding:12px;min-height:82px}.filter-box label{display:block;font-weight:700;margin-bottom:8px}.filter-box input{width:48%;height:32px;border:1px solid var(--line);padding:0 8px}.filter-box select{width:100%;height:32px;border:1px solid var(--line)}
.tabs{max-width:1600px;margin:16px auto 0;display:flex;gap:5px}.tab{border:0;padding:10px 18px;border-radius:5px 5px 0 0;font-weight:800;color:white;cursor:pointer}.tab.naver{background:var(--green)}.tab.coupang{background:var(--red)}.tab.compare{background:var(--navy)}.tab.inactive{opacity:.45}.table-wrap{max-width:1600px;margin:auto;overflow:auto;border:1px solid var(--line);max-height:650px}.data-table{border-collapse:collapse;min-width:1500px;width:100%;font-size:12px}.data-table th,.data-table td{border-right:1px solid #e1e6ec;border-bottom:1px solid #e7ebef;padding:8px 7px;text-align:center;white-space:nowrap}.data-table thead th{position:sticky;top:0;z-index:2;background:var(--navy);color:white}.data-table thead th.naver-head{background:var(--green)}.data-table thead th.coupang-head{background:var(--red)}.data-table td:first-child{text-align:left;font-weight:700}.empty{padding:60px;text-align:center;color:#788591}.badge{display:inline-block;padding:3px 7px;border:1px solid #cbd8ec;background:#f4f7ff;color:#43679d;border-radius:12px}.bad{color:#be2437}.good{color:#0d8c3a}.note{white-space:normal;min-width:220px;text-align:left!important;color:#66727c}
.modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.38);display:none;align-items:center;justify-content:center;z-index:20}.modal{width:520px;background:white;border-radius:10px;padding:22px;box-shadow:0 16px 50px rgba(0,0,0,.25)}.modal h2{margin-top:0}.field{margin:13px 0}.field label{display:block;font-weight:700;margin-bottom:6px}.field input{width:100%;height:38px;border:1px solid var(--line);padding:0 10px}.modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:18px}.modal-actions button{border:0;border-radius:6px;padding:10px 14px;cursor:pointer}.primary{background:var(--blue);color:white}.secondary{background:#e9edf2}.test-result{margin-top:12px;padding:10px;background:#f5f7fa;white-space:pre-wrap}
@media(max-width:900px){.category-bar{grid-template-columns:1fr 1fr}.filter-grid{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<header><div class="brand">셀러라이프 <span>소싱리포트</span></div><div class="head-actions"><button id="settingsBtn">API 설정</button></div></header>
<section class="hero"><h1>카테고리 소싱</h1><div class="category-bar">
<select id="cat1"><option value="">1차 분류</option></select><select id="cat2" disabled><option value="">2차 분류</option></select><select id="cat3" disabled><option value="">3차 분류</option></select><select id="cat4" disabled><option value="">4차 분류</option></select><button class="search-btn" id="searchBtn" title="선택 단계까지 조사">⌕</button></div>
<div class="helper">1차~4차 중 <strong>어느 단계에서든</strong> 검색할 수 있습니다. 선택한 단계의 하위 분류와 관련 키워드를 자동 생성합니다.</div></section>
<main><div class="status" id="status">카테고리를 하나 이상 선택한 뒤 돋보기를 누르세요.</div>
<section class="filters"><div class="filter-head">필터</div><div class="filter-grid">
<div class="filter-box"><label>키워드</label><input id="keywordFilter" placeholder="포함 검색어"></div>
<div class="filter-box"><label>네이버 통합검색 최근지수</label><input id="searchMin" type="number" placeholder="최소"> - <input id="searchMax" type="number" placeholder="최대"></div>
<div class="filter-box"><label>네이버 쇼핑 클릭 최근지수</label><input id="clickMin" type="number" placeholder="최소"> - <input id="clickMax" type="number" placeholder="최대"></div>
<div class="filter-box"><label>보기</label><select id="rowLimit"><option>10</option><option selected>20</option><option>30</option></select></div>
</div></section>
<div class="tabs"><button class="tab naver" data-tab="naver">N 네이버 상품</button><button class="tab coupang inactive" data-tab="coupang">C 쿠팡</button><button class="tab compare inactive" data-tab="compare">통합 비교</button></div>
<div class="table-wrap" id="tableWrap"><div class="empty">아직 조사 결과가 없습니다.</div></div></main>
<div class="modal-backdrop" id="modal"><div class="modal"><h2>NAVER API HUB 설정</h2>
<p>필요한 API는 <b>검색어 트렌드</b>와 <b>쇼핑 인사이트</b> 두 개입니다. 별도의 쇼핑 검색 API는 사용하지 않습니다.</p>
<div class="field"><label>Client ID</label><input id="clientId"></div><div class="field"><label>Client Secret</label><input id="clientSecret" type="password" placeholder="기존 값 유지 시 비워두기"></div><div class="field"><label>쇼핑 인사이트 기본 카테고리 코드</label><input id="categoryCode" value="50000000"></div>
<div class="modal-actions"><button class="secondary" id="closeModal">닫기</button><button class="secondary" id="testBtn">저장 후 연결 테스트</button><button class="primary" id="saveBtn">저장</button></div><div class="test-result" id="testResult">아직 테스트하지 않았습니다.</div></div></div>
<script>
const TREE={
"패션의류":{"남성의류":{"바지":["작업복바지","카고바지","청바지","슬랙스","트레이닝바지"],"상의":["티셔츠","셔츠","조끼","점퍼"],"정장":["정장세트","정장바지"]},"여성의류":{"바지":["청바지","슬랙스","레깅스"],"상의":["티셔츠","블라우스","니트"]}},
"패션잡화":{"신발":{"기능화":["안전화","작업화","등산화"],"신발용품":["깔창","신발끈","뒤꿈치패드"]},"가방":{"남성가방":["백팩","크로스백"],"여행가방":["캐리어","보스턴백"]}},
"화장품/미용":{"헤어케어":{"미용연습용품":["마네킹헤드","마네킹스탠드","커트가위"],"헤어기기":["드라이기","고데기"]},"스킨케어":{"기초화장품":["스킨","로션","크림"]}},
"디지털/가전":{"생활가전":{"청소기":["무선청소기","차량용청소기"],"계절가전":["선풍기","전기요"]},"휴대폰용품":{"보호용품":["케이스","보호필름"],"충전용품":["충전기","케이블"]}},
"가구/인테리어":{"수납가구":{"선반":["철제선반","벽선반"],"수납함":["리빙박스","서랍장"]},"침구":{"침구소품":["베개","매트리스커버"]}},
"출산/육아":{"유아용품":{"외출용품":["유모차용품","기저귀가방"],"생활용품":["턱받이","수유쿠션"]}},
"식품":{"건강식품":{"영양식품":["단백질음료","에너지바"]},"간편식":{"즉석식품":["컵밥","즉석국"]}},
"스포츠/레저":{"등산":{"등산용품":["등산스틱","등산장갑","무릎보호대"],"등산의류":["등산바지","등산조끼"]},"헬스":{"운동용품":["손목보호대","리프팅스트랩","악력기"]}},
"생활/건강":{"공구":{"작업용품":["공구벨트","공구파우치","무릎패드"],"보호용품":["안전모패드","작업장갑"]},"생활용품":{"세탁용품":["세탁망","수선패치"],"욕실용품":["욕실화","배수구필터"]}},
"여가/생활편의":{"자동차용품":{"차량관리":["세차타월","차량수납함"]},"반려동물":{"생활용품":["배변봉투","급수기"]}}
};
const TOP_CODES={"패션의류":"50000000","패션잡화":"50000001","화장품/미용":"50000002","디지털/가전":"50000003","가구/인테리어":"50000004","출산/육아":"50000005","식품":"50000006","스포츠/레저":"50000007","생활/건강":"50000008","여가/생활편의":"50000009"};
const $=id=>document.getElementById(id);let data=[];let activeTab="naver";
function fillSelect(el,values,placeholder){el.innerHTML=`<option value="">${placeholder}</option>`;values.forEach(v=>el.add(new Option(v,v)));el.disabled=!values.length}
fillSelect($("cat1"),Object.keys(TREE),"1차 분류");
function resetFrom(level){for(let i=level;i<=4;i++)fillSelect($("cat"+i),[],i+"차 분류")}
$("cat1").onchange=()=>{resetFrom(2);const n=TREE[$("cat1").value];if(n)fillSelect($("cat2"),Object.keys(n),"2차 분류")};
$("cat2").onchange=()=>{resetFrom(3);const n=TREE[$("cat1").value]?.[$("cat2").value];if(n)fillSelect($("cat3"),Object.keys(n),"3차 분류")};
$("cat3").onchange=()=>{resetFrom(4);const n=TREE[$("cat1").value]?.[$("cat2").value]?.[$("cat3").value];if(n)fillSelect($("cat4"),Array.isArray(n)?n:Object.keys(n),"4차 분류")};
function selectedPath(){return [1,2,3,4].map(i=>$("cat"+i).value).filter(Boolean)}
function nodeFor(path){let n=TREE;for(const p of path)n=n?.[p];return n}
function descendants(node,out=[]){if(Array.isArray(node)){out.push(...node);return out}if(node&&typeof node==='object')for(const [k,v] of Object.entries(node)){out.push(k);descendants(v,out)}return out}
function keywordsFor(path,limit){const node=nodeFor(path);const last=path[path.length-1];let words=[last,...descendants(node)];const modifiers=["여름","겨울","빅사이즈","남성","여성","작업용"];
if(path.length>=3){for(const m of modifiers)words.push(m+last)}
words=words.map(x=>String(x).trim()).filter(x=>x&&x.length>=2);return [...new Set(words)].slice(0,limit)}
function fmt(v){return v===null||v===undefined||v===''?'—':Number(v).toLocaleString('ko-KR')}
function pct(v){return v===null||v===undefined?'—':`${v>0?'+':''}${v}%`}
function trendValue(obj,key='latest'){return obj?.available?obj[key]:null}
function passes(r){const q=$("keywordFilter").value.trim();if(q&&!r.keyword.includes(q))return false;const s=trendValue(r.naver.searchTrend),c=trendValue(r.naver.shoppingClickTrend);const sm=Number($("searchMin").value),sx=Number($("searchMax").value),cm=Number($("clickMin").value),cx=Number($("clickMax").value);if($("searchMin").value&&!(s>=sm))return false;if($("searchMax").value&&!(s<=sx))return false;if($("clickMin").value&&!(c>=cm))return false;if($("clickMax").value&&!(c<=cx))return false;return true}
function naverTable(rows){return `<table class="data-table"><thead><tr><th>키워드</th><th>카테고리</th><th class="naver-head">통합검색 최근지수</th><th class="naver-head">통합검색 3개월 변화</th><th class="naver-head">쇼핑 클릭 최근지수</th><th class="naver-head">쇼핑 클릭 3개월 변화</th><th class="naver-head">공개 상품 수</th><th class="naver-head">표본 수</th><th class="naver-head">최저가</th><th class="naver-head">중앙가</th><th class="naver-head">평균가</th><th>데이터 상태</th></tr></thead><tbody>${rows.map(r=>{const s=r.naver.searchTrend||{},c=r.naver.shoppingClickTrend||{},p=r.naver.products||{};return `<tr><td>${r.keyword}</td><td>${r.categoryPath.join(' &gt; ')}</td><td>${fmt(trendValue(s))}</td><td>${pct(trendValue(s,'change3m'))}</td><td>${fmt(trendValue(c))}</td><td>${pct(trendValue(c,'change3m'))}</td><td>${fmt(p.total)}</td><td>${fmt(p.sampleProducts)}</td><td>${fmt(p.prices?.min)}</td><td>${fmt(p.prices?.median)}</td><td>${fmt(p.prices?.avg)}</td><td class="note">${p.error||'공개 검색화면 표본'}${s.error?'<br>검색추이: '+s.error:''}${c.error?'<br>쇼핑클릭: '+c.error:''}</td></tr>`}).join('')}</tbody></table>`}
function coupangTable(rows){return `<table class="data-table"><thead><tr><th>키워드</th><th>카테고리</th><th class="coupang-head">쿠팡 검색량</th><th class="coupang-head">쿠팡 클릭 추이</th><th class="coupang-head">상품 표본 수</th><th class="coupang-head">최저가</th><th class="coupang-head">중앙가</th><th class="coupang-head">평균가</th><th class="coupang-head">최대 리뷰</th><th class="coupang-head">평균 리뷰</th><th class="coupang-head">로켓 표식</th><th class="coupang-head">광고 표식</th><th>데이터 상태</th></tr></thead><tbody>${rows.map(r=>{const p=r.coupang.products||{};return `<tr><td>${r.keyword}</td><td>${r.categoryPath.join(' &gt; ')}</td><td><span class="badge">공개 API 없음</span></td><td><span class="badge">공개 API 없음</span></td><td>${fmt(p.sampleProducts)}</td><td>${fmt(p.prices?.min)}</td><td>${fmt(p.prices?.median)}</td><td>${fmt(p.prices?.avg)}</td><td>${fmt(p.reviews?.max)}</td><td>${fmt(p.reviews?.avg)}</td><td>${fmt(p.rocketCount)}</td><td>${fmt(p.adCount)}</td><td class="note">${p.error||'공개 검색화면 표본'}<br>네이버 트렌드를 쿠팡 값으로 재사용하지 않습니다.</td></tr>`}).join('')}</tbody></table>`}
function compareTable(rows){return `<table class="data-table"><thead><tr><th>키워드</th><th>네이버 통합검색 지수</th><th>네이버 쇼핑 클릭 지수</th><th>네이버 중앙가</th><th>쿠팡 중앙가</th><th>네이버 표본</th><th>쿠팡 표본</th><th>판정 메모</th></tr></thead><tbody>${rows.map(r=>{const np=r.naver.products||{},cp=r.coupang.products||{};const nm=np.prices?.median,cm=cp.prices?.median;let note='두 플랫폼의 공개 상품표본을 비교하세요.';if(nm&&cm)note=cm>nm?'쿠팡 중앙가가 더 높음':'네이버 중앙가가 더 높거나 같음';return `<tr><td>${r.keyword}</td><td>${fmt(trendValue(r.naver.searchTrend))}</td><td>${fmt(trendValue(r.naver.shoppingClickTrend))}</td><td>${fmt(nm)}</td><td>${fmt(cm)}</td><td>${fmt(np.sampleProducts)}</td><td>${fmt(cp.sampleProducts)}</td><td class="note">${note}<br>쿠팡 수요 추이는 공개되지 않음</td></tr>`}).join('')}</tbody></table>`}
function render(){const rows=data.filter(passes);if(!rows.length){$("tableWrap").innerHTML='<div class="empty">조건에 맞는 조사 결과가 없습니다.</div>';return}$("tableWrap").innerHTML=activeTab==='naver'?naverTable(rows):activeTab==='coupang'?coupangTable(rows):compareTable(rows)}
for(const id of ['keywordFilter','searchMin','searchMax','clickMin','clickMax'])$(id).oninput=render;
document.querySelectorAll('.tab').forEach(btn=>btn.onclick=()=>{activeTab=btn.dataset.tab;document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('inactive',x!==btn));render()});
$("searchBtn").onclick=async()=>{const path=selectedPath();if(!path.length){$("status").textContent='1차 분류를 먼저 선택하세요.';return}const limit=Number($("rowLimit").value);const keywords=keywordsFor(path,limit);if(!keywords.length){$("status").textContent='조사할 키워드를 만들지 못했습니다.';return}$("status").textContent=`${path.join(' > ')} 기준 ${keywords.length}개 키워드 조사 중...`;$("searchBtn").disabled=true;try{const categoryCode=TOP_CODES[path[0]]||'50000000';const res=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keywords,categoryCode,categoryPath:path})});const body=await res.json();if(!res.ok)throw new Error(body.error||'조사 실패');data=body.results||[];$("status").textContent=`조사 완료: ${data.length}개 키워드. 네이버 추이는 네이버 기준이며 쿠팡 추이 값은 생성하지 않습니다.`;render()}catch(e){$("status").textContent='오류: '+e.message}finally{$("searchBtn").disabled=false}};
const modal=$("modal");$("settingsBtn").onclick=async()=>{modal.style.display='flex';const r=await fetch('/api/config');const c=await r.json();$("clientId").value=c.clientId||'';$("clientSecret").value='';$("categoryCode").value=c.categoryCode||'50000000'};$("closeModal").onclick=()=>modal.style.display='none';
async function saveConfig(){const payload={clientId:$("clientId").value,clientSecret:$("clientSecret").value,categoryCode:$("categoryCode").value};const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok)throw new Error('설정 저장 실패');return r.json()}
$("saveBtn").onclick=async()=>{try{await saveConfig();$("testResult").textContent='저장했습니다.'}catch(e){$("testResult").textContent=e.message}};
$("testBtn").onclick=async()=>{try{await saveConfig();$("testResult").textContent='연결 테스트 중...';const r=await fetch('/api/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({categoryCode:$("categoryCode").value})});const t=await r.json();$("testResult").textContent=`검색어 트렌드: ${t.searchTrend.ok?'정상':'실패'}\n${t.searchTrend.message}\n\n쇼핑 인사이트: ${t.shoppingInsight.ok?'정상':'실패'}\n${t.shoppingInsight.message}\n\n쇼핑 검색 테스트는 존재하지 않으므로 실행하지 않습니다.`}catch(e){$("testResult").textContent='테스트 실패: '+e.message}};
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = "SellerGap/0.4.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, obj: Any, status: int = 200) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return json.loads(raw)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            payload = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/api/config":
            config = load_config()
            self.send_json({
                "clientId": config.get("clientId", ""),
                "hasSecret": bool(config.get("clientSecret")),
                "categoryCode": config.get("categoryCode", "50000000"),
            })
            return
        self.send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            body = self.read_json()
        except (json.JSONDecodeError, ValueError):
            self.send_json({"error": "잘못된 JSON 요청입니다."}, 400)
            return

        if parsed.path == "/api/config":
            saved = save_config(body)
            self.send_json({"ok": True, "clientId": saved["clientId"], "categoryCode": saved["categoryCode"]})
            return

        if parsed.path == "/api/test":
            config = load_config()
            category_code = str(body.get("categoryCode") or config.get("categoryCode") or "50000000")
            self.send_json(test_apis(config, category_code))
            return

        if parsed.path == "/api/analyze":
            keywords = [str(x).strip() for x in body.get("keywords", []) if str(x).strip()]
            keywords = list(dict.fromkeys(keywords))[:30]
            if not keywords:
                self.send_json({"error": "조사할 키워드가 없습니다."}, 400)
                return
            category_path = [str(x) for x in body.get("categoryPath", [])]
            category_code = str(body.get("categoryCode") or TOP_CATEGORY_CODES.get(category_path[0], "50000000"))
            config = load_config()
            results: list[dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(analyze_keyword, kw, category_code, config): kw for kw in keywords}
                for future in as_completed(futures):
                    keyword = futures[future]
                    try:
                        item = future.result()
                    except Exception as exc:  # keep other keyword rows alive
                        item = {
                            "keyword": keyword,
                            "naver": {"searchTrend": {"available": False, "error": str(exc)}, "shoppingClickTrend": {"available": False}, "products": {"available": False}},
                            "coupang": {"products": {"available": False, "error": str(exc)}},
                        }
                    item["categoryPath"] = category_path
                    results.append(item)
            order = {kw: i for i, kw in enumerate(keywords)}
            results.sort(key=lambda x: order.get(x.get("keyword", ""), 9999))
            self.send_json({"results": results, "categoryCode": category_code})
            return

        self.send_json({"error": "Not found"}, 404)


def open_browser() -> None:
    time.sleep(0.8)
    webbrowser.open(f"http://{HOST}:{PORT}")


def main() -> None:
    ensure_data()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Seller Gap v0.4.1: http://{HOST}:{PORT}")
    threading.Thread(target=open_browser, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
