"""
Бесплатное обогащение карточки товара:
- описание (Wikipedia RU/EN + DuckDuckGo Instant Answer)
- ссылка на сайт производителя / страницу модели
- сниппеты «отзывов» из выдачи DuckDuckGo (без API-ключа)
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, quote_plus

import httpx

UA = (
    "Mozilla/5.0 (compatible; PCComparator/1.0; +https://github.com/DoctorGreeb/pc-component-comparator)"
)

MANUFACTURER_HOME: dict[str, str] = {
    "amd": "https://www.amd.com/en.html",
    "intel": "https://www.intel.com/",
    "nvidia": "https://www.nvidia.com/",
    "asus": "https://www.asus.com/",
    "asrock": "https://www.asrock.com/",
    "msi": "https://www.msi.com/",
    "gigabyte": "https://www.gigabyte.com/",
    "aorus": "https://www.aorus.com/",
    "corsair": "https://www.corsair.com/",
    "kingston": "https://www.kingston.com/",
    "samsung": "https://www.samsung.com/",
    "wd": "https://www.westerndigital.com/",
    "western digital": "https://www.westerndigital.com/",
    "seagate": "https://www.seagate.com/",
    "crucial": "https://www.crucial.com/",
    "g.skill": "https://www.gskill.com/",
    "gskill": "https://www.gskill.com/",
    "teamgroup": "https://www.teamgroupinc.com/",
    "patriot": "https://www.patriotmemory.com/",
    "thermalright": "https://www.thermalright.com/",
    "deepcool": "https://www.deepcool.com/",
    "cooler master": "https://www.coolermaster.com/",
    "be quiet": "https://www.bequiet.com/",
    "be quiet!": "https://www.bequiet.com/",
    "seasonic": "https://seasonic.com/",
    "fsp": "https://www.fsp-group.com/",
    "thermaltake": "https://www.thermaltake.com/",
    "fractal design": "https://www.fractal-design.com/",
    "lian li": "https://lian-li.com/",
    "nzxt": "https://nzxt.com/",
    "palit": "https://www.palit.com/",
    "gainward": "https://www.gainward.com/",
    "zotac": "https://www.zotac.com/",
    "powercolor": "https://www.powercolor.com/",
    "sapphire": "https://www.sapphiretech.com/",
    "xfx": "https://www.xfxforce.com/",
    "inno3d": "https://www.inno3d.com/",
    "pny": "https://www.pny.com/",
    "colorful": "https://en.colorful.cn/",
    "biostar": "https://www.biostar.com.tw/",
    "supermicro": "https://www.supermicro.com/",
    "huawei": "https://www.huawei.com/",
    "apacer": "https://www.apacer.com/",
    "adata": "https://www.adata.com/",
    "transcend": "https://www.transcend-info.com/",
}


def _clean_query(name: str) -> str:
    s = re.sub(r"\s+", " ", (name or "").strip())
    s = re.sub(r"[「」【】\[\](){}]", " ", s)
    return s[:120].strip()


def _brand_key(brand: str | None, name: str) -> str:
    b = (brand or "").strip().lower()
    if b:
        return b
    n = (name or "").lower()
    for k in sorted(MANUFACTURER_HOME.keys(), key=len, reverse=True):
        if n.startswith(k) or f" {k} " in f" {n} ":
            return k
    return ""


def manufacturer_links(brand: str | None, name: str, model: str | None = None) -> dict[str, str | None]:
    key = _brand_key(brand, name)
    home = MANUFACTURER_HOME.get(key)
    q = _clean_query(name)
    site_search = None
    if home:
        try:
            from urllib.parse import urlparse

            host = urlparse(home).netloc.replace("www.", "")
            site_search = f"https://www.google.com/search?q={quote_plus(q + ' site:' + host)}"
        except Exception:
            site_search = home
    web_search = f"https://www.google.com/search?q={quote_plus(q + ' official')}"
    return {
        "brand_key": key or None,
        "manufacturer_home": home,
        "manufacturer_model_search": site_search or web_search,
        "web_search": web_search,
    }


async def fetch_wikipedia_summary(name: str) -> dict[str, Any] | None:
    q = _clean_query(name)
    if len(q) < 3:
        return None
    titles = [q]
    parts = q.split()
    if len(parts) > 2:
        titles.append(" ".join(parts[1:4]))
        titles.append(" ".join(parts[:3]))

    async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": UA}, follow_redirects=True) as client:
        for lang in ("ru", "en"):
            for title in titles:
                url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title, safe='')}"
                try:
                    r = await client.get(url)
                    if r.status_code != 200:
                        continue
                    data = r.json()
                    if data.get("type") in ("disambiguation", "no-extract"):
                        continue
                    extract = (data.get("extract") or "").strip()
                    if len(extract) < 40:
                        continue
                    return {
                        "source": f"wikipedia_{lang}",
                        "title": data.get("title") or title,
                        "extract": extract,
                        "url": (data.get("content_urls") or {}).get("desktop", {}).get("page"),
                        "thumbnail": ((data.get("thumbnail") or {}).get("source")),
                    }
                except Exception:
                    continue
    return None


async def fetch_ddg_abstract(name: str) -> dict[str, Any] | None:
    q = _clean_query(name)
    url = "https://api.duckduckgo.com/"
    params = {"q": q, "format": "json", "no_html": 1, "skip_disambig": 1}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": UA}) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return None
            data = r.json()
            abstract = (data.get("AbstractText") or "").strip()
            if len(abstract) < 40:
                for t in data.get("RelatedTopics") or []:
                    if isinstance(t, dict) and len((t.get("Text") or "")) > 40:
                        abstract = t["Text"]
                        break
            if len(abstract) < 40:
                return None
            return {
                "source": "duckduckgo",
                "title": data.get("Heading") or q,
                "extract": abstract,
                "url": data.get("AbstractURL") or None,
            }
    except Exception:
        return None


async def fetch_review_snippets(name: str, limit: int = 6) -> list[dict[str, str]]:
    q = _clean_query(name)
    queries = [f"{q} отзыв", f"{q} review", f"{q} обзор"]
    results: list[dict[str, str]] = []
    seen: set[str] = set()

    async with httpx.AsyncClient(
        timeout=10.0,
        headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"},
        follow_redirects=True,
    ) as client:
        for query in queries:
            if len(results) >= limit:
                break
            try:
                r = await client.get("https://html.duckduckgo.com/html/", params={"q": query})
                if r.status_code != 200:
                    continue
                html = r.text
                titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, flags=re.I | re.S)
                snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)', html, flags=re.I | re.S)
                hrefs = re.findall(r'class="result__a"[^>]*href="([^"]+)"', html, flags=re.I)
                n = max(len(titles), len(snippets), len(hrefs))
                for i in range(n):
                    if len(results) >= limit:
                        break
                    title = re.sub(r"<[^>]+>", "", titles[i] if i < len(titles) else "").strip()
                    snip = re.sub(r"<[^>]+>", "", snippets[i] if i < len(snippets) else "").strip()
                    href = hrefs[i] if i < len(hrefs) else ""
                    m = re.search(r"uddg=([^&]+)", href)
                    if m:
                        from urllib.parse import unquote

                        href = unquote(m.group(1))
                    key = (title + snip)[:80].lower()
                    if not snip or key in seen or len(snip) < 30:
                        continue
                    seen.add(key)
                    results.append(
                        {
                            "title": title[:160] or "Источник",
                            "snippet": snip[:400],
                            "url": href[:500] if href.startswith("http") else "",
                            "query": query,
                        }
                    )
            except Exception:
                continue
    return results


async def enrich_product_page(
    name: str,
    brand: str | None = None,
    model: str | None = None,
    existing_description: str | None = None,
) -> dict[str, Any]:
    links = manufacturer_links(brand, name, model)
    description = (existing_description or "").strip()
    description_source = "database" if description else None
    description_url = None

    if len(description) < 60:
        wiki = await fetch_wikipedia_summary(name)
        if wiki and wiki.get("extract"):
            description = wiki["extract"]
            description_source = wiki.get("source")
            description_url = wiki.get("url")
        else:
            ddg = await fetch_ddg_abstract(name)
            if ddg and ddg.get("extract"):
                description = ddg["extract"]
                description_source = ddg.get("source")
                description_url = ddg.get("url")

    reviews = await fetch_review_snippets(name, limit=6)

    return {
        "description": description or None,
        "description_source": description_source,
        "description_url": description_url,
        "manufacturer_home": links.get("manufacturer_home"),
        "manufacturer_model_url": links.get("manufacturer_model_search"),
        "web_search_url": links.get("web_search"),
        "reviews": reviews,
        "reviews_note": (
            "Сниппеты из открытой веб-выдачи по запросу «отзыв / review / обзор». "
            "Это не модерируемые отзывы магазинов."
            if reviews
            else "По открытым источникам сниппетов не найдено."
        ),
    }


def _plain_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    from html import unescape
    return re.sub(r"\\s+", " ", unescape(value)).strip()


def _spec_name_match(expected: str, candidate: str) -> bool:
    def tokens(value: str) -> set[str]:
        return set(re.findall(r"[a-zа-яё0-9]+", (value or "").lower()))
    left, right = tokens(expected), tokens(candidate)
    if not left or not right:
        return False
    if left <= right or right <= left:
        return True
    # Ignore generic words, but require several model-specific tokens.
    generic = {"видеокарта", "процессор", "материнская", "плата", "память", "оперативная", "карта", "купить", "цена"}
    left -= generic
    right -= generic
    if len(left) < 2:
        return False
    return len(left & right) / len(left) >= 0.7


def _extract_spec_rows(page: str) -> dict[str, str]:
    specs: dict[str, str] = {}
    for row in re.findall(r"(?is)<tr\\b[^>]*>(.*?)</tr>", page):
        cells = re.findall(r"(?is)<t[dh]\\b[^>]*>(.*?)</t[dh]>", row)
        if len(cells) < 2:
            continue
        key = _plain_html(cells[0])[:90].strip(" :")
        value = _plain_html(cells[1])[:300]
        if not key or not value or key.lower() == value.lower():
            continue
        if len(key) < 2 or len(value) < 1:
            continue
        if key.lower() in {"характеристика", "параметр", "свойство", "specification", "feature"}:
            continue
        specs[key] = value

    # Some manufacturer/store pages use definition lists instead of tables.
    for block in re.findall(r"(?is)<dt\\b[^>]*>(.*?)</dt>\\s*<dd\\b[^>]*>(.*?)</dd>", page):
        key, value = _plain_html(block[0])[:90], _plain_html(block[1])[:300]
        if key and value and key.lower() != value.lower():
            specs.setdefault(key, value)
    return {k: v for k, v in specs.items() if k and v}


async def search_specs_on_web(name: str, brand: str | None = None, model: str | None = None) -> dict[str, Any] | None:
    """Fallback: search public web results and extract actual key/value rows from product pages."""
    query = _clean_query(" ".join(x for x in (brand, model, name, "характеристики") if x))
    if len(query) < 3:
        return None
    headers = {
        "User-Agent": UA,
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=6.0), headers=headers, follow_redirects=True) as client:
        try:
            response = await client.get("https://html.duckduckgo.com/html/", params={"q": query})
            response.raise_for_status()
        except Exception:
            return None

        result_blocks = re.findall(r'(?is)<div[^>]+class="[^"]*result[^"]*"[^>]*>(.*?)(?=<div[^>]+class="[^"]*result[^"]*"|$)', response.text)
        candidates: list[tuple[str, str]] = []
        seen_urls: set[str] = set()
        for block in result_blocks:
            link = re.search(r'(?is)<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
            if not link:
                continue
            href = link.group(1)
            title = _plain_html(link.group(2))
            redirect = re.search(r"[?&]uddg=([^&]+)", href)
            if redirect:
                from urllib.parse import unquote
                href = unquote(redirect.group(1))
            if not href.startswith("http") or href in seen_urls:
                continue
            seen_urls.add(href)
            if _spec_name_match(name, title):
                candidates.append((title, href))
            if len(candidates) >= 7:
                break

        for title, url in candidates:
            try:
                page_response = await client.get(url)
                if page_response.status_code != 200 or "text/html" not in page_response.headers.get("content-type", ""):
                    continue
                specs = _extract_spec_rows(page_response.text)
                if len(specs) >= 3:
                    return {
                        "specs": specs,
                        "source": "web",
                        "source_title": title,
                        "source_url": str(page_response.url),
                    }
            except Exception:
                continue
    return None
