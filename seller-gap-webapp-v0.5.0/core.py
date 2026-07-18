from __future__ import annotations

import base64
import hashlib
import hmac
import html as html_lib
import json
import re
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import sync_playwright
except Exception:  # Playwright is optional until install.bat is run.
    sync_playwright = None

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CONFIG_FILE = DATA_DIR / "config.json"
CACHE_FILE = DATA_DIR / "cache.json"
CATEGORY_FILE = DATA_DIR / "categories.json"
BROWSER_PROFILE = DATA_DIR / "browser-profile"

NAVER_API_HUB_BASE = "https://naverapihub.apigw.ntruss.com"
SEARCH_AD_BASE = "https://api.searchad.naver.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

DEFAULT_CONFIG: dict[str, Any] = {
    "naverApiHub": {
        "clientId": "",
        "clientSecret": "",
        "defaultCategoryCode": "50000000",
    },
    "searchAd": {
        "apiKey": "",
        "secretKey": "",
        "customerId": "",
    },
    "collector": {
        "coupangMode": "browser",
        "browserVisible": True,
        "sampleLimit": 72,
    },
}

CONFIG_LOCK = threading.Lock()
CACHE_LOCK = threading.Lock()


def ensure_data() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    if not CACHE_FILE.exists():
        CACHE_FILE.write_text("{}", encoding="utf-8")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict[str, Any]:
    ensure_data()
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    return deep_merge(DEFAULT_CONFIG, saved if isinstance(saved, dict) else {})


def public_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    return {
        "naverApiHub": {
            "clientId": config["naverApiHub"].get("clientId", ""),
            "hasSecret": bool(config["naverApiHub"].get("clientSecret")),
            "defaultCategoryCode": config["naverApiHub"].get("defaultCategoryCode", "50000000"),
        },
        "searchAd": {
            "apiKey": config["searchAd"].get("apiKey", ""),
            "customerId": config["searchAd"].get("customerId", ""),
            "hasSecret": bool(config["searchAd"].get("secretKey")),
        },
        "collector": config.get("collector", {}),
        "playwrightInstalled": sync_playwright is not None,
    }


def save_config(payload: dict[str, Any]) -> dict[str, Any]:
    with CONFIG_LOCK:
        current = load_config()
        incoming = deep_merge(current, payload if isinstance(payload, dict) else {})

        # Blank secret fields mean "keep existing value".
        incoming_naver = incoming.get("naverApiHub", {})
        payload_naver = (payload or {}).get("naverApiHub", {})
        if not str(payload_naver.get("clientSecret", "")).strip():
            incoming_naver["clientSecret"] = current["naverApiHub"].get("clientSecret", "")

        incoming_ad = incoming.get("searchAd", {})
        payload_ad = (payload or {}).get("searchAd", {})
        if not str(payload_ad.get("secretKey", "")).strip():
            incoming_ad["secretKey"] = current["searchAd"].get("secretKey", "")

        collector = incoming.get("collector", {})
        collector["coupangMode"] = "browser" if collector.get("coupangMode") == "browser" else "direct"
        collector["browserVisible"] = bool(collector.get("browserVisible", True))
        try:
            collector["sampleLimit"] = max(12, min(100, int(collector.get("sampleLimit", 72))))
        except (TypeError, ValueError):
            collector["sampleLimit"] = 72

        CONFIG_FILE.write_text(json.dumps(incoming, ensure_ascii=False, indent=2), encoding="utf-8")
        return public_config(incoming)


def load_categories() -> dict[str, Any]:
    try:
        value = json.loads(CATEGORY_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_cache() -> dict[str, Any]:
    ensure_data()
    try:
        value = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(cache: dict[str, Any]) -> None:
    with CACHE_LOCK:
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail: Any = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw[:800]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"연결 실패: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("API 응답이 JSON 형식이 아닙니다.") from exc


def fetch_html(url: str, timeout: int = 18) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"공개 검색화면 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"공개 검색화면 연결 실패: {exc.reason}") from exc


def naver_hub_headers(config: dict[str, Any]) -> dict[str, str]:
    hub = config.get("naverApiHub", {})
    client_id = str(hub.get("clientId", "")).strip()
    secret = str(hub.get("clientSecret", "")).strip()
    if not client_id or not secret:
        raise RuntimeError("NAVER API HUB Client ID와 Client Secret을 먼저 저장하세요.")
    return {
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": secret,
        "Content-Type": "application/json",
    }


def trend_date_range() -> tuple[str, str]:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=1095)
    return start.isoformat(), end.isoformat()


def summarize_trend(data: list[dict[str, Any]]) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    for item in data:
        try:
            points.append({"period": str(item.get("period", "")), "ratio": round(float(item.get("ratio", 0)), 5)})
        except (TypeError, ValueError):
            continue
    if not points:
        return {"available": False, "points": []}

    ratios = [point["ratio"] for point in points]
    latest = ratios[-1]
    recent3 = ratios[-3:]
    previous3 = ratios[-6:-3]
    recent3_avg = sum(recent3) / len(recent3)
    previous3_avg = sum(previous3) / len(previous3) if previous3 else 0
    change3 = ((recent3_avg - previous3_avg) / previous3_avg * 100) if previous3_avg else None
    yoy = None
    if len(ratios) >= 13 and ratios[-13] > 0:
        yoy = (latest - ratios[-13]) / ratios[-13] * 100
    peak_index = max(range(len(ratios)), key=ratios.__getitem__)
    recent12 = ratios[-12:]
    seasonality = "높음" if recent12 and (max(recent12) - min(recent12) >= 45) else "중간" if recent12 and (max(recent12) - min(recent12) >= 20) else "낮음"
    return {
        "available": True,
        "latest": round(latest, 2),
        "recent3Avg": round(recent3_avg, 2),
        "change3m": round(change3, 2) if change3 is not None else None,
        "yoy": round(yoy, 2) if yoy is not None else None,
        "peakPeriod": points[peak_index]["period"],
        "seasonality": seasonality,
        "points": points,
        "basis": "조회 기간 내 최댓값을 100으로 둔 상대지수",
    }


def search_trend(keyword: str, config: dict[str, Any]) -> dict[str, Any]:
    start, end = trend_date_range()
    response = json_request(
        f"{NAVER_API_HUB_BASE}/search-trend/v1/search",
        method="POST",
        headers=naver_hub_headers(config),
        payload={
            "startDate": start,
            "endDate": end,
            "timeUnit": "month",
            "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}],
        },
    )
    results = response.get("results") or []
    if not results:
        return {"available": False, "error": "검색어 트렌드 결과가 없습니다.", "points": []}
    return summarize_trend(results[0].get("data") or [])


def shopping_click_trend(keyword: str, category_code: str, config: dict[str, Any]) -> dict[str, Any]:
    start, end = trend_date_range()
    response = json_request(
        f"{NAVER_API_HUB_BASE}/shopping/v1/category/keywords",
        method="POST",
        headers=naver_hub_headers(config),
        payload={
            "startDate": start,
            "endDate": end,
            "timeUnit": "month",
            "category": category_code,
            "keyword": [{"name": keyword, "param": [keyword]}],
        },
    )
    results = response.get("results") or []
    if not results:
        return {"available": False, "error": "쇼핑 클릭 추이 결과가 없습니다.", "points": []}
    return summarize_trend(results[0].get("data") or [])


def search_ad_headers(method: str, uri: str, config: dict[str, Any]) -> dict[str, str]:
    search_ad = config.get("searchAd", {})
    api_key = str(search_ad.get("apiKey", "")).strip()
    secret_key = str(search_ad.get("secretKey", "")).strip()
    customer_id = str(search_ad.get("customerId", "")).strip()
    if not api_key or not secret_key or not customer_id:
        raise RuntimeError("네이버 검색광고 API Key, Secret Key, Customer ID가 필요합니다.")
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}.{method}.{uri}"
    signature = base64.b64encode(
        hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")
    return {
        "X-Timestamp": timestamp,
        "X-API-KEY": api_key,
        "X-Customer": customer_id,
        "X-Signature": signature,
    }


def parse_search_count(value: Any) -> tuple[int, str]:
    text = str(value or "0").strip()
    if "<" in text:
        return 0, text.replace(" ", "")
    digits = re.sub(r"[^0-9]", "", text)
    return (int(digits), f"{int(digits):,}") if digits else (0, "0")


def search_ad_keyword_tool(keyword: str, config: dict[str, Any]) -> dict[str, Any]:
    uri = "/keywordstool"
    query = urllib.parse.urlencode({"hintKeywords": keyword, "showDetail": "1"})
    response = json_request(
        f"{SEARCH_AD_BASE}{uri}?{query}",
        headers=search_ad_headers("GET", uri, config),
    )
    rows = response.get("keywordList") or []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        pc, pc_display = parse_search_count(row.get("monthlyPcQcCnt"))
        mobile, mobile_display = parse_search_count(row.get("monthlyMobileQcCnt"))
        normalized.append(
            {
                "keyword": str(row.get("relKeyword", "")),
                "monthlyPc": pc,
                "monthlyPcDisplay": pc_display,
                "monthlyMobile": mobile,
                "monthlyMobileDisplay": mobile_display,
                "monthlyTotal": pc + mobile,
                "monthlyTotalDisplay": f"{pc + mobile:,}" if pc + mobile else ("<20" if "<" in pc_display or "<" in mobile_display else "0"),
                "competition": row.get("compIdx"),
                "averageDepth": row.get("plAvgDepth"),
            }
        )
    exact = next((row for row in normalized if row["keyword"].replace(" ", "").lower() == keyword.replace(" ", "").lower()), None)
    return {
        "available": bool(normalized),
        "exact": exact,
        "related": sorted(normalized, key=lambda row: row["monthlyTotal"], reverse=True)[:30],
    }


def clean_number(value: Any) -> int | None:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if not digits:
        return None
    number = int(digits)
    return number if number >= 0 else None


def strip_tags(value: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def ratio(part: int, total: int) -> float | None:
    return round(part / total * 100, 1) if total else None


def summarize_products(products: list[dict[str, Any]], source: str, url: str, total: int | None = None) -> dict[str, Any]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in products:
        name = str(item.get("name", "")).strip()
        key = f"{name}|{item.get('price')}|{item.get('url')}"
        if not name or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    prices = [int(item["price"]) for item in unique if isinstance(item.get("price"), int) and 100 <= item["price"] <= 100_000_000]
    reviews = [int(item["review"]) for item in unique if isinstance(item.get("review"), int) and item["review"] >= 0]
    delivery = Counter(str(item.get("delivery", "normal")) for item in unique)
    ads = sum(1 for item in unique if item.get("ad"))
    count = len(unique)
    return {
        "available": count > 0,
        "source": source,
        "sourceUrl": url,
        "capturedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sampleCount": count,
        "reportedTotal": total,
        "prices": {
            "count": len(prices),
            "min": min(prices) if prices else None,
            "median": int(statistics.median(prices)) if prices else None,
            "avg": int(sum(prices) / len(prices)) if prices else None,
            "max": max(prices) if prices else None,
        },
        "reviews": {
            "count": len(reviews),
            "total": sum(reviews) if reviews else 0,
            "max": max(reviews) if reviews else None,
            "avg": int(sum(reviews) / len(reviews)) if reviews else None,
        },
        "delivery": {
            "rocket": delivery.get("rocket", 0),
            "sellerRocket": delivery.get("sellerRocket", 0),
            "normal": delivery.get("normal", 0),
            "overseas": delivery.get("overseas", 0),
            "rocketRatio": ratio(delivery.get("rocket", 0), count),
            "sellerRocketRatio": ratio(delivery.get("sellerRocket", 0), count),
            "normalRatio": ratio(delivery.get("normal", 0), count),
            "overseasRatio": ratio(delivery.get("overseas", 0), count),
        },
        "ads": {"count": ads, "ratio": ratio(ads, count)},
        "products": unique[:40],
        "sampleNotice": f"검색결과에서 실제로 읽힌 상품 {count}개 기준",
    }


def naver_public_products(keyword: str) -> dict[str, Any]:
    url = "https://search.shopping.naver.com/ns/search?" + urllib.parse.urlencode({"query": keyword})
    try:
        text = fetch_html(url)
    except RuntimeError as exc:
        return {"available": False, "error": str(exc), "sourceUrl": url, "products": []}

    total = None
    for pattern in [r'"total"\s*:\s*(\d+)', r'"totalCount"\s*:\s*(\d+)', r'"productCount"\s*:\s*(\d+)']:
        match = re.search(pattern, text)
        if match:
            total = int(match.group(1))
            break

    names = re.findall(r'"(?:productTitle|productName|title)"\s*:\s*"([^"\\]{2,160})"', text, flags=re.I)
    prices = re.findall(r'"(?:lowPrice|salePrice|price)"\s*:\s*"?(\d{3,})', text, flags=re.I)
    products: list[dict[str, Any]] = []
    for index, name in enumerate(names[:100]):
        price = clean_number(prices[index]) if index < len(prices) else None
        products.append({"name": html_lib.unescape(name), "price": price, "review": None, "delivery": "normal", "ad": False, "url": url})
    summary = summarize_products(products, "네이버쇼핑 공개 검색화면", url, total)
    if not summary["available"]:
        summary["error"] = "페이지는 열렸지만 상품 목록을 추출하지 못했습니다."
    return summary


def parse_coupang_html(keyword: str, text: str, source: str = "쿠팡 공개 검색화면") -> dict[str, Any]:
    url = "https://www.coupang.com/np/search?" + urllib.parse.urlencode({"q": keyword})
    cards = re.findall(
        r'<li\b[^>]*class="[^"]*(?:search-product|baby-product)[^"]*"[^>]*>(.*?)</li>',
        text,
        flags=re.I | re.S,
    )
    products: list[dict[str, Any]] = []
    for card in cards[:100]:
        card_text = strip_tags(card)
        name_match = re.search(r'class="[^"]*name[^"]*"[^>]*>(.*?)</', card, flags=re.I | re.S)
        price_match = re.search(r'class="[^"]*price-value[^"]*"[^>]*>\s*([0-9,]+)', card, flags=re.I)
        review_match = re.search(r'(?:rating-total-count|review-count)[^>]*>\s*\(?([0-9,]+)\)?', card, flags=re.I)
        link_match = re.search(r'href="([^"]+)"', card, flags=re.I)
        name = strip_tags(name_match.group(1)) if name_match else card_text[:120]
        price = clean_number(price_match.group(1)) if price_match else None
        review = clean_number(review_match.group(1)) if review_match else None
        if "판매자로켓" in card_text:
            delivery = "sellerRocket"
        elif "해외" in card_text or "로켓직구" in card_text:
            delivery = "overseas"
        elif "로켓" in card_text:
            delivery = "rocket"
        else:
            delivery = "normal"
        href = html_lib.unescape(link_match.group(1)) if link_match else ""
        if href.startswith("/"):
            href = "https://www.coupang.com" + href
        products.append(
            {
                "name": name,
                "price": price,
                "review": review,
                "delivery": delivery,
                "ad": bool(re.search(r'(^|\s)광고($|\s)|ad-badge|isAd', card_text, flags=re.I)),
                "url": href or url,
            }
        )

    # JSON fallback used when Coupang changes visible card markup.
    if not products:
        names = re.findall(r'"(?:name|productName)"\s*:\s*"([^"\\]{3,160})"', text, flags=re.I)
        prices = re.findall(r'"(?:salePrice|price)"\s*:\s*(\d{3,})', text, flags=re.I)
        reviews = re.findall(r'"(?:ratingCount|reviewCount)"\s*:\s*(\d+)', text, flags=re.I)
        for index, name in enumerate(names[:72]):
            products.append(
                {
                    "name": html_lib.unescape(name),
                    "price": clean_number(prices[index]) if index < len(prices) else None,
                    "review": clean_number(reviews[index]) if index < len(reviews) else None,
                    "delivery": "normal",
                    "ad": False,
                    "url": url,
                }
            )

    summary = summarize_products(products, source, url)
    if not summary["available"]:
        summary["error"] = "쿠팡 검색결과에서 상품 카드가 확인되지 않았습니다. 로그인 또는 브라우저 수집을 사용하세요."
    return summary


def coupang_direct_products(keyword: str) -> dict[str, Any]:
    url = "https://www.coupang.com/np/search?" + urllib.parse.urlencode({"q": keyword})
    try:
        text = fetch_html(url)
    except RuntimeError as exc:
        return {"available": False, "error": str(exc), "sourceUrl": url, "products": []}
    return parse_coupang_html(keyword, text, "쿠팡 서버 직접 요청 표본")


COUPANG_EXTRACT_SCRIPT = r"""
(limit) => {
  const selectors = ['li.search-product', 'li[class*="search-product"]', 'li[class*="baby-product"]', '[data-product-id]'];
  const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
  const seen = new Set();
  const out = [];
  const number = (value) => {
    const match = String(value || '').replace(/,/g, '').match(/\d+/);
    return match ? Number(match[0]) : null;
  };
  for (const el of nodes) {
    if (out.length >= limit) break;
    const link = el.querySelector('a[href]');
    const href = link ? new URL(link.getAttribute('href'), location.origin).href : location.href;
    if (seen.has(href)) continue;
    seen.add(href);
    const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
    const nameEl = el.querySelector('.name, [class*="name"], [class*="title"]');
    const priceEl = el.querySelector('.price-value, [class*="price-value"], strong[class*="price"]');
    const reviewEl = el.querySelector('.rating-total-count, [class*="review"], [class*="rating-total"]');
    const name = (nameEl?.textContent || text).replace(/\s+/g, ' ').trim().slice(0, 180);
    const price = number(priceEl?.textContent || '');
    const review = number(reviewEl?.textContent || '');
    let delivery = 'normal';
    if (text.includes('판매자로켓')) delivery = 'sellerRocket';
    else if (text.includes('로켓직구') || text.includes('해외배송')) delivery = 'overseas';
    else if (text.includes('로켓')) delivery = 'rocket';
    out.push({name, price, review, delivery, ad: /(^|\s)광고($|\s)/.test(text), url: href});
  }
  return out;
}
"""


def coupang_browser_batch(keywords: list[str], config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if sync_playwright is None:
        return {
            keyword: {
                "available": False,
                "error": "Playwright가 설치되지 않았습니다. install.bat을 먼저 실행하세요.",
                "products": [],
            }
            for keyword in keywords
        }

    collector = config.get("collector", {})
    visible = bool(collector.get("browserVisible", True))
    sample_limit = max(12, min(100, int(collector.get("sampleLimit", 72))))
    output: dict[str, dict[str, Any]] = {}
    with sync_playwright() as playwright:
        launch_args = {
            "user_data_dir": str(BROWSER_PROFILE),
            "headless": not visible,
            "locale": "ko-KR",
            "viewport": {"width": 1440, "height": 1000},
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        try:
            context = playwright.chromium.launch_persistent_context(channel="chrome", **launch_args)
        except Exception:
            context = playwright.chromium.launch_persistent_context(**launch_args)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            for keyword in keywords:
                url = "https://www.coupang.com/np/search?" + urllib.parse.urlencode({"q": keyword})
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    page.wait_for_timeout(2200)
                    products = page.evaluate(COUPANG_EXTRACT_SCRIPT, sample_limit)
                    summary = summarize_products(products or [], "로그인 세션 Chrome 검색결과", url)
                    if not summary["available"]:
                        summary["error"] = "상품 카드가 없습니다. 열린 Chrome에서 쿠팡 로그인 후 다시 조사하세요."
                    output[keyword] = summary
                except Exception as exc:
                    output[keyword] = {"available": False, "error": f"브라우저 수집 실패: {exc}", "sourceUrl": url, "products": []}
        finally:
            context.close()
    return output


def category_code_for_path(path: list[str], categories: dict[str, Any], config: dict[str, Any]) -> str:
    if path:
        top = categories.get(path[0], {})
        code = str(top.get("code", "")).strip()
        if code:
            return code
    return str(config.get("naverApiHub", {}).get("defaultCategoryCode", "50000000"))


def category_node(categories: dict[str, Any], path: list[str]) -> dict[str, Any]:
    node: dict[str, Any] = {"children": categories}
    for name in path:
        children = node.get("children", {}) if isinstance(node, dict) else {}
        node = children.get(name, {}) if isinstance(children, dict) else {}
    return node if isinstance(node, dict) else {}


def descendant_terms(node: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for keyword in node.get("keywords", []) if isinstance(node.get("keywords"), list) else []:
        result.append(str(keyword))
    children = node.get("children", {}) if isinstance(node.get("children"), dict) else {}
    for name, child in children.items():
        result.append(str(name))
        if isinstance(child, dict):
            result.extend(descendant_terms(child))
    return result


def generate_keywords(path: list[str], included_keyword: str, limit: int, categories: dict[str, Any]) -> list[str]:
    node = category_node(categories, path)
    seeds = descendant_terms(node)
    base = path[-1] if path else ""
    if base:
        seeds.insert(0, base)
    if not seeds and base:
        seeds = [base, f"여름{base}", f"대용량{base}", f"접이식{base}", f"빅사이즈{base}"]
    included = included_keyword.strip()
    if included:
        combined: list[str] = []
        for seed in seeds or [base]:
            if included.replace(" ", "") in seed.replace(" ", ""):
                combined.append(seed)
            else:
                combined.extend([f"{included}{seed}", f"{seed}{included}"])
        seeds = combined
    cleaned: list[str] = []
    seen: set[str] = set()
    for seed in seeds:
        value = re.sub(r"\s+", "", str(seed)).strip()
        if len(value) < 2 or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
        if len(cleaned) >= limit:
            break
    return cleaned


def safe_call(function: Any, *args: Any) -> dict[str, Any]:
    try:
        return function(*args)
    except RuntimeError as exc:
        return {"available": False, "error": str(exc)}
    except Exception as exc:
        return {"available": False, "error": f"예상하지 못한 오류: {exc}"}


def token_frequency(titles: list[str]) -> list[dict[str, Any]]:
    stop = {
        "무료배송", "국내배송", "로켓배송", "쿠팡", "네이버", "정품", "공식", "세트", "상품", "당일",
        "여성", "남성", "여자", "남자", "용품", "추천", "신상", "할인",
    }
    counter: Counter[str] = Counter()
    for title in titles:
        for token in re.findall(r"[가-힣A-Za-z0-9]{2,18}", title):
            normalized = token.lower()
            if normalized in stop or normalized.isdigit():
                continue
            counter[normalized] += 1
    return [{"keyword": word, "count": count} for word, count in counter.most_common(30)]


def analyze_naver(keyword: str, category_code: str, config: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "searchTrend": safe_call(search_trend, keyword, config),
        "shoppingClickTrend": safe_call(shopping_click_trend, keyword, category_code, config),
        "products": naver_public_products(keyword),
    }
    search_ad = config.get("searchAd", {})
    if all(str(search_ad.get(key, "")).strip() for key in ("apiKey", "secretKey", "customerId")):
        result["searchVolume"] = safe_call(search_ad_keyword_tool, keyword, config)
    else:
        result["searchVolume"] = {"available": False, "reason": "네이버 검색광고 API가 설정되지 않았습니다."}
    return result


def analyze_category(payload: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    categories = load_categories()
    path = [str(value).strip() for value in payload.get("path", []) if str(value).strip()]
    if not path:
        raise RuntimeError("1차 분류를 선택하세요.")
    try:
        limit = max(1, min(30, int(payload.get("limit", 12))))
    except (TypeError, ValueError):
        limit = 12
    included = str(payload.get("includedKeyword", ""))
    keywords = generate_keywords(path, included, limit, categories)
    if not keywords:
        raise RuntimeError("선택한 분류에서 조사 키워드를 생성하지 못했습니다.")
    category_code = category_code_for_path(path, categories, config)

    naver_results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(5, len(keywords))) as executor:
        future_map = {executor.submit(analyze_naver, keyword, category_code, config): keyword for keyword in keywords}
        for future in as_completed(future_map):
            keyword = future_map[future]
            try:
                naver_results[keyword] = future.result()
            except Exception as exc:
                naver_results[keyword] = {"error": str(exc)}

    collector = config.get("collector", {})
    if collector.get("coupangMode") == "browser":
        coupang_results = coupang_browser_batch(keywords, config)
    else:
        coupang_results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=min(4, len(keywords))) as executor:
            future_map = {executor.submit(coupang_direct_products, keyword): keyword for keyword in keywords}
            for future in as_completed(future_map):
                keyword = future_map[future]
                try:
                    coupang_results[keyword] = future.result()
                except Exception as exc:
                    coupang_results[keyword] = {"available": False, "error": str(exc), "products": []}

    rows = [
        {
            "keyword": keyword,
            "categoryPath": path,
            "categoryCode": category_code,
            "naver": naver_results.get(keyword, {}),
            "coupang": {"products": coupang_results.get(keyword, {})},
        }
        for keyword in keywords
    ]
    cache = load_cache()
    for row in rows:
        cache[row["keyword"]] = {"savedAt": datetime.now().isoformat(timespec="seconds"), "data": row}
    save_cache(cache)
    return {
        "path": path,
        "categoryCode": category_code,
        "keywords": keywords,
        "rows": rows,
        "collector": public_config(config)["collector"],
    }


def analyze_keyword(payload: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    categories = load_categories()
    keyword = str(payload.get("keyword", "")).strip()
    if not keyword:
        raise RuntimeError("키워드를 입력하세요.")
    path = [str(value).strip() for value in payload.get("categoryPath", []) if str(value).strip()]
    category_code = str(payload.get("categoryCode", "")).strip() or category_code_for_path(path, categories, config)
    naver = analyze_naver(keyword, category_code, config)

    collector = config.get("collector", {})
    if collector.get("coupangMode") == "browser":
        coupang_products = coupang_browser_batch([keyword], config).get(keyword, {})
    else:
        coupang_products = coupang_direct_products(keyword)

    titles: list[str] = []
    titles.extend(str(item.get("name", "")) for item in naver.get("products", {}).get("products", []))
    titles.extend(str(item.get("name", "")) for item in coupang_products.get("products", []))
    frequencies = token_frequency(titles)

    related: list[dict[str, Any]] = []
    search_volume = naver.get("searchVolume", {})
    if search_volume.get("available"):
        related = search_volume.get("related", [])[:20]
    else:
        related = [{"keyword": item["keyword"], "count": item["count"]} for item in frequencies[:20]]

    result = {
        "keyword": keyword,
        "categoryPath": path,
        "categoryCode": category_code,
        "naver": naver,
        "coupang": {
            "products": coupang_products,
            "searchDemand": {
                "available": False,
                "reason": "쿠팡 전체 검색량·클릭량은 공개되지 않아 상품 검색결과 통계와 구분합니다.",
            },
        },
        "relatedKeywords": related,
        "titleFrequency": frequencies,
    }
    cache = load_cache()
    cache[keyword] = {"savedAt": datetime.now().isoformat(timespec="seconds"), "data": result}
    save_cache(cache)
    return result


def analyze_uploaded_coupang_html(payload: dict[str, Any]) -> dict[str, Any]:
    keyword = str(payload.get("keyword", "")).strip()
    text = str(payload.get("html", ""))
    if not keyword or not text:
        raise RuntimeError("키워드와 저장한 쿠팡 HTML을 모두 입력하세요.")
    return parse_coupang_html(keyword, text, "사용자가 저장한 쿠팡 검색 페이지")


def test_connections(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if payload:
        save_config(payload)
    config = load_config()
    category_code = str(config.get("naverApiHub", {}).get("defaultCategoryCode", "50000000"))
    tests: dict[str, Any] = {}
    value = safe_call(search_trend, "테스트", config)
    tests["searchTrend"] = {"ok": bool(value.get("available")), "message": value.get("error") or "정상"}
    value = safe_call(shopping_click_trend, "가디건", category_code, config)
    tests["shoppingInsight"] = {"ok": bool(value.get("available")), "message": value.get("error") or "정상"}

    search_ad = config.get("searchAd", {})
    if all(str(search_ad.get(key, "")).strip() for key in ("apiKey", "secretKey", "customerId")):
        value = safe_call(search_ad_keyword_tool, "가디건", config)
        tests["searchAd"] = {"ok": bool(value.get("available")), "message": value.get("error") or "정상"}
    else:
        tests["searchAd"] = {"ok": None, "message": "미설정(선택 기능)"}

    tests["playwright"] = {
        "ok": sync_playwright is not None,
        "message": "설치됨" if sync_playwright is not None else "미설치: install.bat 실행 필요",
    }
    return {"tests": tests, "settings": public_config(config)}
