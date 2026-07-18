from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
import re
import statistics
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import Counter
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
CONFIG_PATH = DATA_DIR / "config.json"
CATEGORY_PATH = DATA_DIR / "categories.json"
HOST = "127.0.0.1"
PORT = 8000
API_BASE = "https://naverapihub.apigw.ntruss.com"

DATA_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "naverApiHub": {
        "clientId": "",
        "clientSecret": ""
    },
    "analysis": {
        "maxKeywords": 14,
        "naverDisplay": 100,
        "coupangSample": 36,
        "requestTimeout": 15
    }
}

STOPWORDS = {
    "무료배송", "당일배송", "국내배송", "해외배송", "정품", "공식", "신상품", "인기",
    "남성", "여성", "남녀공용", "공용", "추천", "특가", "할인", "대박", "고급",
    "세트", "단품", "선택", "옵션", "색상", "사이즈", "블랙", "화이트", "네이비",
    "그레이", "베이지", "브라운", "레드", "블루", "그린", "상품", "제품", "용품",
    "1개", "2개", "3개", "5개", "10개", "1+1", "기획", "최신", "2026"
}


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> dict[str, Any]:
    config = load_json(CONFIG_PATH, DEFAULT_CONFIG)
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    merged["naverApiHub"].update(config.get("naverApiHub", {}))
    merged["analysis"].update(config.get("analysis", {}))
    return merged


def api_headers(config: dict[str, Any], json_content: bool = False) -> dict[str, str]:
    naver = config.get("naverApiHub", {})
    headers = {
        "X-NCP-APIGW-API-KEY-ID": str(naver.get("clientId", "")).strip(),
        "X-NCP-APIGW-API-KEY": str(naver.get("clientSecret", "")).strip(),
        "User-Agent": "SellerGapSourcing/0.4.0",
        "Accept": "application/json",
    }
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


def request_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
                 payload: Any = None, timeout: int = 15) -> Any:
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body)
        except Exception:
            detail = body[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"네트워크 오류: {exc.reason}") from exc


def request_text(url: str, *, headers: dict[str, str] | None = None, timeout: int = 15) -> str:
    request = urllib.request.Request(url, method="GET")
    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.6,en;q=0.5",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Cache-Control": "no-cache",
    }
    default_headers.update(headers or {})
    for key, value in default_headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {clean_text(body)[:180]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"네트워크 오류: {exc.reason}") from exc


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(re.sub(r"[^0-9.-]", "", str(value))))
    except Exception:
        return default


def round_or_none(value: float | None, digits: int = 1) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def describe_numbers(numbers: list[int | float]) -> dict[str, Any]:
    values = [float(v) for v in numbers if v is not None and float(v) >= 0]
    if not values:
        return {"min": None, "median": None, "average": None, "max": None}
    return {
        "min": round(min(values)),
        "median": round(statistics.median(values)),
        "average": round(statistics.fmean(values)),
        "max": round(max(values)),
    }


def fetch_naver_shop(keyword: str, config: dict[str, Any]) -> dict[str, Any]:
    display = max(1, min(100, to_int(config["analysis"].get("naverDisplay", 100), 100)))
    query = urllib.parse.urlencode({
        "query": keyword,
        "display": display,
        "start": 1,
        "sort": "sim",
        "exclude": "used:rental",
        "format": "json",
    })
    url = f"{API_BASE}/search/v1/shop?{query}"
    data = request_json(
        url,
        headers=api_headers(config),
        timeout=to_int(config["analysis"].get("requestTimeout", 15), 15),
    )
    items = []
    for raw in data.get("items", []):
        title = clean_text(raw.get("title"))
        price = to_int(raw.get("lprice"), 0)
        mall = clean_text(raw.get("mallName"))
        link = str(raw.get("link") or "")
        category = [clean_text(raw.get(f"category{i}")) for i in range(1, 5)]
        is_overseas = any(token in f"{title} {mall} {link}" for token in ("해외", "직구", "구매대행", "global", "aliexpress"))
        is_naver = "naver.com" in link or "스마트스토어" in mall
        items.append({
            "title": title,
            "price": price,
            "mall": mall,
            "link": link,
            "image": raw.get("image"),
            "brand": clean_text(raw.get("brand")),
            "maker": clean_text(raw.get("maker")),
            "category": category,
            "overseas": is_overseas,
            "naverMall": is_naver,
        })
    prices = [item["price"] for item in items if item["price"] > 0]
    counts = Counter(item["mall"] for item in items if item["mall"])
    top_mall_share = (max(counts.values()) / len(items) * 100) if items and counts else 0
    return {
        "status": "ok",
        "total": to_int(data.get("total"), 0),
        "sampleCount": len(items),
        "prices": describe_numbers(prices),
        "overseasCount": sum(1 for item in items if item["overseas"]),
        "domesticCount": sum(1 for item in items if not item["overseas"]),
        "naverMallCount": sum(1 for item in items if item["naverMall"]),
        "mallCount": len(counts),
        "topMallShare": round(top_mall_share, 1),
        "items": items,
    }


def fetch_search_trend(keyword: str, config: dict[str, Any]) -> dict[str, Any]:
    today = dt.date.today()
    start = today.replace(day=1) - dt.timedelta(days=760)
    payload = {
        "startDate": start.isoformat(),
        "endDate": today.isoformat(),
        "timeUnit": "month",
        "keywordGroups": [{"groupName": keyword[:20], "keywords": [keyword]}],
    }
    data = request_json(
        f"{API_BASE}/search-trend/v1/search",
        method="POST",
        headers=api_headers(config, True),
        payload=payload,
        timeout=to_int(config["analysis"].get("requestTimeout", 15), 15),
    )
    points = []
    results = data.get("results") or []
    if results:
        points = results[0].get("data") or []
    ratios = [float(point.get("ratio", 0)) for point in points]
    recent1 = ratios[-1] if ratios else None
    recent3_values = ratios[-3:] if ratios else []
    previous3_values = ratios[-6:-3] if len(ratios) >= 6 else []
    recent3 = statistics.fmean(recent3_values) if recent3_values else None
    previous3 = statistics.fmean(previous3_values) if previous3_values else None
    growth3 = ((recent3 - previous3) / previous3 * 100) if recent3 is not None and previous3 not in (None, 0) else None
    yoy = ((ratios[-1] - ratios[-13]) / ratios[-13] * 100) if len(ratios) >= 13 and ratios[-13] else None
    avg = statistics.fmean(ratios) if ratios else 0
    seasonality = (statistics.pstdev(ratios) / avg * 100) if len(ratios) >= 2 and avg else None
    maximum = max(points, key=lambda x: float(x.get("ratio", 0)), default=None)
    return {
        "status": "ok",
        "recent1": round_or_none(recent1),
        "recent3": round_or_none(recent3),
        "growth3": round_or_none(growth3),
        "yoy": round_or_none(yoy),
        "seasonality": round_or_none(seasonality),
        "peakPeriod": maximum.get("period") if maximum else None,
        "peakIndex": round_or_none(float(maximum.get("ratio", 0))) if maximum else None,
        "points": points,
        "note": "조회 기간 내 상대지수(최댓값 100)이며 절대 검색량이 아닙니다.",
    }


def fetch_shopping_insight(keyword: str, category_code: str, config: dict[str, Any]) -> dict[str, Any]:
    if not re.fullmatch(r"\d{8}", str(category_code or "")):
        return {"status": "skipped", "reason": "8자리 네이버 쇼핑 카테고리 코드가 아님"}
    today = dt.date.today()
    start = today.replace(day=1) - dt.timedelta(days=395)
    payload = {
        "startDate": start.isoformat(),
        "endDate": today.isoformat(),
        "timeUnit": "month",
        "category": str(category_code),
        "keyword": [{"name": keyword[:20], "param": [keyword]}],
    }
    data = request_json(
        f"{API_BASE}/shopping/v1/category/keywords",
        method="POST",
        headers=api_headers(config, True),
        payload=payload,
        timeout=to_int(config["analysis"].get("requestTimeout", 15), 15),
    )
    results = data.get("results") or []
    points = results[0].get("data", []) if results else []
    ratios = [float(point.get("ratio", 0)) for point in points]
    return {
        "status": "ok",
        "recent1": round_or_none(ratios[-1] if ratios else None),
        "recent3": round_or_none(statistics.fmean(ratios[-3:]) if ratios else None),
        "points": points,
        "note": "네이버쇼핑 클릭 상대지수입니다.",
    }


def extract_block_value(block: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, block, re.I | re.S)
        if match:
            return clean_text(match.group(1))
    return ""


def fetch_coupang(keyword: str, config: dict[str, Any]) -> dict[str, Any]:
    url = "https://www.coupang.com/np/search?" + urllib.parse.urlencode({"q": keyword, "channel": "user"})
    raw = request_text(url, timeout=to_int(config["analysis"].get("requestTimeout", 15), 15))
    lowered = raw.lower()
    if "access denied" in lowered or "captcha" in lowered or "robot" in lowered and len(raw) < 30000:
        raise RuntimeError("쿠팡이 자동 조회를 제한했습니다. 잠시 후 다시 시도하거나 브라우저 수동 검증이 필요합니다.")

    blocks = re.findall(r"<li[^>]*class=[\"'][^\"']*search-product[^\"']*[\"'][^>]*>(.*?)</li>", raw, re.I | re.S)
    if not blocks:
        blocks = re.findall(r"<a[^>]*class=[\"'][^\"']*search-product-link[^\"']*[\"'][^>]*>(.*?)</a>", raw, re.I | re.S)
    limit = max(1, min(72, to_int(config["analysis"].get("coupangSample", 36), 36)))
    items = []
    for block in blocks[:limit]:
        title = extract_block_value(block, [
            r"class=[\"'][^\"']*name[^\"']*[\"'][^>]*>(.*?)<",
            r"class=[\"'][^\"']*search-product-name[^\"']*[\"'][^>]*>(.*?)<",
            r"alt=[\"']([^\"']+)[\"']",
        ])
        price_text = extract_block_value(block, [
            r"class=[\"'][^\"']*price-value[^\"']*[\"'][^>]*>(.*?)<",
            r"class=[\"'][^\"']*sale-price[^\"']*[\"'][^>]*>.*?<strong[^>]*>(.*?)<",
        ])
        review_text = extract_block_value(block, [
            r"class=[\"'][^\"']*rating-total-count[^\"']*[\"'][^>]*>(.*?)<",
            r"class=[\"'][^\"']*rating-total-count[^\"']*[\"'][^>]*>\s*\((.*?)\)",
        ])
        recent_text = extract_block_value(block, [
            r"(\d[\d,]*명\s*구매)",
            r"(최근\s*\d[\d,]*개\s*구매)",
            r"(\d[\d,]*개\s*구매)",
        ])
        plain = clean_text(block)
        if not title or not to_int(price_text):
            continue
        items.append({
            "title": title,
            "price": to_int(price_text),
            "reviews": to_int(review_text),
            "recentPurchase": recent_text,
            "rocket": bool(re.search(r"로켓|rocket", plain, re.I)),
            "rocketGrowth": bool(re.search(r"로켓그로스|판매자로켓", plain, re.I)),
            "overseas": bool(re.search(r"해외직구|해외배송|로켓직구", plain, re.I)),
            "ad": bool(re.search(r"광고|ad-badge|sponsored", plain, re.I)),
        })

    total = 0
    total_patterns = [
        r"검색결과\s*([\d,]+)개",
        r"result-total-count[^>]*>\s*([\d,]+)",
        r"totalCount[\"']?\s*[:=]\s*[\"']?([\d,]+)",
    ]
    for pattern in total_patterns:
        match = re.search(pattern, raw, re.I)
        if match:
            total = to_int(match.group(1))
            break
    prices = [item["price"] for item in items]
    reviews = [item["reviews"] for item in items]
    sample = len(items)
    return {
        "status": "ok" if sample else "empty",
        "total": total or None,
        "sampleCount": sample,
        "prices": describe_numbers(prices),
        "reviews": describe_numbers(reviews),
        "rocketCount": sum(1 for item in items if item["rocket"]),
        "rocketGrowthCount": sum(1 for item in items if item["rocketGrowth"]),
        "overseasCount": sum(1 for item in items if item["overseas"]),
        "adCount": sum(1 for item in items if item["ad"]),
        "recentPurchaseCount": sum(1 for item in items if item["recentPurchase"]),
        "items": items,
        "note": "쿠팡 공개 검색화면에서 현재 확인되는 표본입니다. 실제 판매량은 아닙니다.",
    }


def extract_keywords_from_titles(titles: list[str], leaf_name: str) -> list[str]:
    token_counter: Counter[str] = Counter()
    pair_counter: Counter[str] = Counter()
    leaf_tokens = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", leaf_name))
    for title in titles:
        cleaned = re.sub(r"[^가-힣A-Za-z0-9+ ]", " ", clean_text(title))
        tokens = [token for token in cleaned.split() if 2 <= len(token) <= 15]
        tokens = [token for token in tokens if token not in STOPWORDS and token not in leaf_tokens and not token.isdigit()]
        for token in set(tokens):
            token_counter[token] += 1
        for i in range(len(tokens) - 1):
            pair = f"{tokens[i]} {tokens[i + 1]}"
            if len(pair) <= 24:
                pair_counter[pair] += 1
    candidates = []
    for phrase, count in pair_counter.most_common(10):
        if count >= 2:
            candidates.append(phrase)
    for token, count in token_counter.most_common(15):
        if count >= 2:
            candidates.append(f"{token} {leaf_name}" if leaf_name not in token else token)
    return candidates


def find_leaf(category_tree: dict[str, Any], path_codes: list[str]) -> dict[str, Any] | None:
    nodes = category_tree.get("categories", [])
    found = None
    for code in path_codes:
        found = next((node for node in nodes if str(node.get("code")) == str(code)), None)
        if not found:
            return None
        nodes = found.get("children", [])
    return found


def discover_keywords(path_codes: list[str], path_names: list[str], config: dict[str, Any]) -> dict[str, Any]:
    category_tree = load_json(CATEGORY_PATH, {"categories": [], "globalModifiers": []})
    leaf = find_leaf(category_tree, path_codes)
    if not leaf:
        raise RuntimeError("선택한 카테고리를 찾을 수 없습니다.")
    leaf_name = clean_text(leaf.get("name") or (path_names[-1] if path_names else ""))
    seeds = [clean_text(x) for x in leaf.get("seeds", []) if clean_text(x)]
    if leaf_name and leaf_name not in seeds:
        seeds.insert(0, leaf_name)

    source_titles: list[str] = []
    naver_error = None
    coupang_error = None
    try:
        naver = fetch_naver_shop(seeds[0], config)
        source_titles.extend(item["title"] for item in naver.get("items", []))
    except Exception as exc:
        naver_error = str(exc)
    try:
        coupang = fetch_coupang(seeds[0], config)
        source_titles.extend(item["title"] for item in coupang.get("items", []))
    except Exception as exc:
        coupang_error = str(exc)

    extracted = extract_keywords_from_titles(source_titles, leaf_name)
    ordered = []
    seen = set()
    for keyword in seeds + extracted:
        normalized = re.sub(r"\s+", " ", keyword).strip()
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    max_keywords = max(4, min(30, to_int(config["analysis"].get("maxKeywords", 14), 14)))
    return {
        "category": {
            "pathCodes": path_codes,
            "pathNames": path_names,
            "leaf": leaf_name,
            "naverCategoryCode": next((code for code in reversed(path_codes) if re.fullmatch(r"\d{8}", str(code))), ""),
        },
        "keywords": ordered[:max_keywords],
        "sourceTitleCount": len(source_titles),
        "warnings": [message for message in [naver_error, coupang_error] if message],
    }


def competition_score_naver(result: dict[str, Any]) -> float | None:
    if result.get("status") != "ok":
        return None
    total = max(0, to_int(result.get("total"), 0))
    total_score = min(55, math.log10(total + 1) / 6 * 55) if total else 0
    concentration = min(25, float(result.get("topMallShare") or 0) / 100 * 25)
    overseas_ratio = (result.get("overseasCount", 0) / max(1, result.get("sampleCount", 0)))
    domestic_pressure = (1 - overseas_ratio) * 20
    return round(min(100, total_score + concentration + domestic_pressure), 1)


def competition_score_coupang(result: dict[str, Any]) -> float | None:
    if result.get("status") not in ("ok", "empty"):
        return None
    sample = max(1, to_int(result.get("sampleCount"), 0))
    total = to_int(result.get("total"), 0)
    count_score = min(45, math.log10(total + 1) / 6 * 45) if total else min(20, sample / 36 * 20)
    rocket_score = result.get("rocketCount", 0) / sample * 30
    ad_score = result.get("adCount", 0) / sample * 15
    review_max = (result.get("reviews") or {}).get("max") or 0
    review_score = min(10, math.log10(review_max + 1) / 5 * 10)
    return round(min(100, count_score + rocket_score + ad_score + review_score), 1)


def analyze_keyword(keyword: str, category_code: str, config: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"keyword": keyword, "errors": {}}
    try:
        result["trend"] = fetch_search_trend(keyword, config)
    except Exception as exc:
        result["trend"] = {"status": "error", "error": str(exc)}
        result["errors"]["trend"] = str(exc)
    try:
        result["shoppingInsight"] = fetch_shopping_insight(keyword, category_code, config)
    except Exception as exc:
        result["shoppingInsight"] = {"status": "error", "error": str(exc)}
        result["errors"]["shoppingInsight"] = str(exc)
    try:
        naver = fetch_naver_shop(keyword, config)
        naver["competitionScore"] = competition_score_naver(naver)
        result["naver"] = naver
    except Exception as exc:
        result["naver"] = {"status": "error", "error": str(exc), "competitionScore": None}
        result["errors"]["naver"] = str(exc)
    try:
        coupang = fetch_coupang(keyword, config)
        coupang["competitionScore"] = competition_score_coupang(coupang)
        result["coupang"] = coupang
    except Exception as exc:
        result["coupang"] = {"status": "error", "error": str(exc), "competitionScore": None}
        result["errors"]["coupang"] = str(exc)
    return result


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = to_int(self.headers.get("Content-Length"), 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise RuntimeError("요청 JSON 형식이 올바르지 않습니다.")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "version": "0.4.0"})
            return
        if parsed.path == "/api/categories":
            self.send_json(load_json(CATEGORY_PATH, {"categories": []}))
            return
        if parsed.path == "/api/config":
            config = load_config()
            safe = json.loads(json.dumps(config))
            secret = safe["naverApiHub"].get("clientSecret", "")
            safe["naverApiHub"]["clientSecret"] = "********" if secret else ""
            safe["naverApiHub"]["configured"] = bool(safe["naverApiHub"].get("clientId") and secret)
            self.send_json(safe)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            body = self.read_json()
            if parsed.path == "/api/config":
                config = load_config()
                incoming = body.get("naverApiHub", {})
                if incoming.get("clientId") is not None:
                    config["naverApiHub"]["clientId"] = str(incoming.get("clientId", "")).strip()
                secret = str(incoming.get("clientSecret", "")).strip()
                if secret and secret != "********":
                    config["naverApiHub"]["clientSecret"] = secret
                if body.get("analysis"):
                    config["analysis"].update(body["analysis"])
                save_json(CONFIG_PATH, config)
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/config/test":
                config = load_config()
                if not config["naverApiHub"].get("clientId") or not config["naverApiHub"].get("clientSecret"):
                    raise RuntimeError("NAVER API HUB Client ID와 Client Secret을 먼저 저장하세요.")
                checks = {}
                try:
                    checks["searchTrend"] = {"ok": fetch_search_trend("깔창", config).get("status") == "ok"}
                except Exception as exc:
                    checks["searchTrend"] = {"ok": False, "error": str(exc)}
                try:
                    shop = fetch_naver_shop("깔창", config)
                    checks["shoppingSearch"] = {"ok": shop.get("status") == "ok", "sample": shop.get("sampleCount", 0)}
                except Exception as exc:
                    checks["shoppingSearch"] = {"ok": False, "error": str(exc)}
                self.send_json({"ok": all(item.get("ok") for item in checks.values()), "checks": checks})
                return
            if parsed.path == "/api/discover":
                config = load_config()
                result = discover_keywords(
                    [str(x) for x in body.get("pathCodes", [])],
                    [str(x) for x in body.get("pathNames", [])],
                    config,
                )
                self.send_json(result)
                return
            if parsed.path == "/api/analyze-keyword":
                keyword = clean_text(body.get("keyword"))
                if not keyword:
                    raise RuntimeError("키워드가 비어 있습니다.")
                result = analyze_keyword(keyword, str(body.get("categoryCode", "")), load_config())
                self.send_json(result)
                return
            self.send_json({"error": "존재하지 않는 API입니다."}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)


def open_browser() -> None:
    webbrowser.open(f"http://{HOST}:{PORT}")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"셀러 갭 소싱 v0.4.0 실행: http://{HOST}:{PORT}")
    print("종료하려면 이 창에서 Ctrl+C를 누르세요.")
    threading.Timer(0.8, open_browser).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
