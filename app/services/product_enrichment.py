"""
Обогащение карточек товара: описание, обзоры и автоматический поиск характеристик.
"""
from __future__ import annotations

import json
import re
from html import unescape
from typing import Any
from urllib.parse import quote, quote_plus, unquote, urlparse

import httpx

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

MANUFACTURER_HOME = {
    "amd": "https://www.amd.com/en.html", "intel": "https://www.intel.com/",
    "nvidia": "https://www.nvidia.com/", "asus": "https://www.asus.com/",
    "asrock": "https://www.asrock.com/", "msi": "https://www.msi.com/",
    "gigabyte": "https://www.gigabyte.com/", "corsair": "https://www.corsair.com/",
    "kingston": "https://www.kingston.com/", "samsung": "https://www.samsung.com/",
    "western digital": "https://www.westerndigital.com/", "seagate": "https://www.seagate.com/",
    "crucial": "https://www.crucial.com/", "g.skill": "https://www.gskill.com/",
    "thermalright": "https://www.thermalright.com/", "deepcool": "https://www.deepcool.com/",
    "cooler master": "https://www.coolermaster.com/", "be quiet": "https://www.bequiet.com/",
    "seasonic": "https://seasonic.com/", "thermaltake": "https://www.thermaltake.com/",
    "fractal design": "https://www.fractal-design.com/", "lian li": "https://lian-li.com/",
    "nzxt": "https://nzxt.com/", "palit": "https://www.palit.com/",
    "zotac": "https://www.zotac.com/", "sapphire": "https://www.sapphiretech.com/",
    "adata": "https://www.adata.com/",
}


def _clean_query(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[「」【】\[\](){}]", " ", value or "")).strip()[:180]


def _plain_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", value or "")
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _brand_key(brand: str | None, name: str) -> str:
    value = (brand or "").strip().lower()
    if value:
        return value
    lower = (name or "").lower()
    return next((key for key in sorted(MANUFACTURER_HOME, key=len, reverse=True) if key in lower), "")


def manufacturer_links(brand: str | None, name: str, model: str | None = None) -> dict[str, str | None]:
    key = _brand_key(brand, name)
    home = MANUFACTURER_HOME.get(key)
    query = _clean_query(" ".join(x for x in (brand, model, name) if x))
    host = urlparse(home).netloc.replace("www.", "") if home else ""
    return {
        "brand_key": key or None, "manufacturer_home": home,
        "manufacturer_model_search": f"https://www.google.com/search?q={quote_plus(query + (' site:' + host if host else ' official'))}",
        "web_search": f"https://www.google.com/search?q={quote_plus(query)}",
    }


async def fetch_wikipedia_summary(name: str) -> dict[str, Any] | None:
    query = _clean_query(name)
    async with httpx.AsyncClient(timeout=7, headers={"User-Agent": UA}, follow_redirects=True) as client:
        for lang in ("ru", "en"):
            try:
                response = await client.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(query, safe='')}")
                if response.status_code == 200:
                    data = response.json()
                    extract = (data.get("extract") or "").strip()
                    if len(extract) >= 40 and data.get("type") not in ("disambiguation", "no-extract"):
                        return {"source": f"wikipedia_{lang}", "extract": extract,
                                "url": (data.get("content_urls") or {}).get("desktop", {}).get("page")}
            except Exception:
                continue
    return None


async def fetch_ddg_abstract(name: str) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=7, headers={"User-Agent": UA}) as client:
            response = await client.get("https://api.duckduckgo.com/", params={
                "q": _clean_query(name), "format": "json", "no_html": 1, "skip_disambig": 1})
            data = response.json() if response.status_code == 200 else {}
            text = (data.get("AbstractText") or "").strip()
            if len(text) >= 40:
                return {"source": "duckduckgo", "extract": text, "url": data.get("AbstractURL")}
    except Exception:
        pass
    return None


async def _search_results(client: httpx.AsyncClient, query: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    try:
        response = await client.get("https://html.duckduckgo.com/html/", params={"q": query})
        if response.status_code == 200:
            html = response.text
            # Parse each result container so title, URL and snippet stay associated.
            blocks = re.findall(r'(?is)<div[^>]+class="[^"]*result[^"]*results_links[^"]*"[^>]*>.*?</div>\s*</div>', html)
            if not blocks:
                blocks = re.findall(r'(?is)<div[^>]+class="[^"]*result[^"]*"[^>]*>.*?(?=<div[^>]+class="[^"]*result[^"]*"|</body>)', html)
            for block in blocks:
                anchor = re.search(r'(?is)<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
                if not anchor:
                    continue
                href = unescape(anchor.group(1))
                redirect = re.search(r"[?&]uddg=([^&]+)", href)
                if redirect:
                    href = unquote(redirect.group(1))
                title = _plain_html(anchor.group(2))
                snippet_match = re.search(r'(?is)class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|td|div)', block)
                snippet = _plain_html(snippet_match.group(1)) if snippet_match else _plain_html(block)
                if href.startswith("http"):
                    results.append({"title": title, "snippet": snippet[:1000], "url": href})
    except Exception:
        pass

    # Bing is a second independent search source, not an API-key service.
    try:
        response = await client.get("https://www.bing.com/search", params={"q": query})
        if response.status_code == 200:
            for block in re.findall(r'(?is)<li[^>]+class="[^"]*b_algo[^"]*"[^>]*>.*?</li>', response.text):
                match = re.search(r'(?is)<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
                if match:
                    snippet_match = re.search(r'(?is)<p[^>]*>(.*?)</p>', block)
                    results.append({"title": _plain_html(match.group(2)),
                                    "snippet": _plain_html(snippet_match.group(1)) if snippet_match else "",
                                    "url": unescape(match.group(1))})
    except Exception:
        pass
    return results


def _model_codes(*values: str | None) -> set[str]:
    text = " ".join(v or "" for v in values).upper()
    codes = re.findall(r"(?<![A-Z0-9])[A-Z]{1,8}[- ]?[A-Z0-9]{2,}(?:[- ][A-Z0-9]{1,8})?(?![A-Z0-9])", text)
    return {re.sub(r"[^A-Z0-9]", "", code) for code in codes if len(re.sub(r"[^A-Z0-9]", "", code)) >= 4}


def _matches_product(title: str, name: str, brand: str | None, model: str | None) -> bool:
    candidate = re.sub(r"[^a-zа-яё0-9]", "", (title or "").lower())
    codes = _model_codes(model, name)
    if codes and any(code.lower() in candidate for code in codes):
        return True
    brand_tokens = set(re.findall(r"[a-zа-яё0-9]+", (brand or "").lower()))
    name_tokens = set(re.findall(r"[a-zа-яё0-9]+", (name or "").lower()))
    meaningful = {t for t in name_tokens | brand_tokens if len(t) >= 3 and t not in {
        "вентилятор", "кулер", "корпусный", "корпуса", "компьютера", "компьютерный", "для", "купить", "характеристики"}}
    title_tokens = set(re.findall(r"[a-zа-яё0-9]+", (title or "").lower()))
    return bool(meaningful) and len(meaningful & title_tokens) >= min(2, len(meaningful))


def _spec_pairs_from_text(text: str) -> dict[str, str]:
    text = unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    specs: dict[str, str] = {}
    # Search snippets often contain compact "key: value" or "key value" fragments.
    patterns = [
        r"([А-ЯЁA-Z][А-ЯЁA-Zа-яёa-z0-9 /(),.-]{2,55}?)\s*:\s*([^:;|]{1,100})",
        r"(Макс\. скорость вращения|Макс\. воздушный поток|Макс\. уровень шума|Диаметр вентилятора|Количество вентиляторов|Тип подшипника|Коннектор питания|Подсветка|Размеры)\s+([^,;|]{1,80})",
    ]
    for pattern in patterns:
        for key, value in re.findall(pattern, text, flags=re.I):
            key, value = key.strip(" .:-"), value.strip(" .;,:-")
            if 2 <= len(key) <= 60 and 1 <= len(value) <= 100 and key.lower() != value.lower():
                specs.setdefault(key, value)
    return specs


def _extract_spec_rows(page: str) -> dict[str, str]:
    specs: dict[str, str] = {}
    # Correct HTML tag-boundary regexes: \b is a regex boundary, not a literal slash.
    for row in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", page):
        cells = re.findall(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>", row)
        if len(cells) >= 2:
            key, value = _plain_html(cells[0])[:100].strip(" :"), _plain_html(cells[1])[:300]
            if key and value and key.lower() != value.lower():
                specs[key] = value
    for key, value in re.findall(r"(?is)<dt\b[^>]*>(.*?)</dt>\s*<dd\b[^>]*>(.*?)</dd>", page):
        k, v = _plain_html(key)[:100], _plain_html(value)[:300]
        if k and v and k.lower() != v.lower():
            specs.setdefault(k, v)

    # Product pages frequently store characteristics in JSON-LD / hydration JSON.
    for raw in re.findall(r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page):
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                props = node.get("additionalProperty") or node.get("additionalProperties") or []
                if isinstance(props, dict):
                    props = [props]
                for prop in props if isinstance(props, list) else []:
                    if isinstance(prop, dict):
                        key = prop.get("name") or prop.get("propertyID")
                        value = prop.get("value") or prop.get("valueReference")
                        if key and value:
                            specs[str(key)[:100]] = str(value)[:300]
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
            elif isinstance(node, list):
                stack.extend(node)
    return {k: v for k, v in specs.items() if k and v}


async def search_specs_on_web(name: str, brand: str | None = None, model: str | None = None) -> dict[str, Any] | None:
    """Search snippets first, then open matching product pages and parse their spec data."""
    query = _clean_query(" ".join(x for x in (brand, model, name) if x))
    if not query:
        return None
    queries = list(dict.fromkeys([
        f'"{model or name}" характеристики',
        f'"{model or name}" характеристики купить',
        f'{query} характеристики',
        f'{query} specifications',
        f'site:ozon.ru/product {model or name} характеристики',
        f'site:dns-shop.ru {model or name} характеристики',
    ]))
    headers = {"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"}
    seen: set[str] = set()
    candidates: list[dict[str, str]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(18, connect=8), headers=headers, follow_redirects=True) as client:
        for search_query in queries:
            for result in await _search_results(client, search_query):
                url = result["url"]
                if url not in seen and _matches_product(result["title"] + " " + result["snippet"], name, brand, model):
                    seen.add(url)
                    candidates.append(result)
                    # First: extract useful fields directly from the search snippet.
                    snippet_specs = _spec_pairs_from_text(result["snippet"])
                    if len(snippet_specs) >= 3:
                        return {"specs": snippet_specs, "source": "search_snippet",
                                "source_title": result["title"], "source_url": url}
            if len(candidates) >= 20:
                break

        # Then open every matching page; do not stop after the first blocked store.
        for result in candidates[:18]:
            try:
                response = await client.get(result["url"])
                if response.status_code != 200 or "html" not in response.headers.get("content-type", "").lower():
                    continue
                specs = _extract_spec_rows(response.text)
                if len(specs) >= 3:
                    return {"specs": specs, "source": "web_page",
                            "source_title": result["title"], "source_url": str(response.url)}
            except Exception:
                continue
    return None


async def fetch_review_snippets(name: str, limit: int = 6) -> list[dict[str, str]]:
    query = _clean_query(name)
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=9, headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"}, follow_redirects=True) as client:
        for term in (f"{query} отзыв", f"{query} обзор", f"{query} review"):
            for result in await _search_results(client, term):
                key = result["url"]
                if key in seen or len(result["snippet"]) < 25:
                    continue
                seen.add(key)
                results.append({"title": result["title"][:160], "snippet": result["snippet"][:400], "url": key, "query": term})
                if len(results) >= limit:
                    return results
    return results


async def enrich_product_page(name: str, brand: str | None = None, model: str | None = None,
                              existing_description: str | None = None) -> dict[str, Any]:
    links = manufacturer_links(brand, name, model)
    description = (existing_description or "").strip()
    source, source_url = ("database", None) if description else (None, None)
    if len(description) < 60:
        result = await fetch_wikipedia_summary(name) or await fetch_ddg_abstract(name)
        if result:
            description, source, source_url = result["extract"], result.get("source"), result.get("url")
    reviews = await fetch_review_snippets(" ".join(x for x in (brand, model, name) if x), 6)
    return {
        "description": description or None, "description_source": source, "description_url": source_url,
        "manufacturer_home": links["manufacturer_home"], "manufacturer_model_url": links["manufacturer_model_search"],
        "web_search_url": links["web_search"], "reviews": reviews,
        "reviews_note": "Сниппеты из открытой веб-выдачи; это не модерируемые отзывы магазинов." if reviews else "По открытым источникам сниппетов не найдено.",
    }
