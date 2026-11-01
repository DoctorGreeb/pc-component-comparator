"""
Поиск картинок без API-ключа:
1) Wikimedia Commons (MediaWiki API)
2) Openverse (Creative Commons / openverse.org)

Используется, когда у товара нет image_url и нет донора в БД.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

HEADERS = {
    "User-Agent": "PCComparator/0.4.3 (https://github.com/DoctorGreeb/pc-component-comparator; contact via github)",
    "Accept": "application/json",
}

# кэш в памяти на процесс: norm_query → url | None
_CACHE: dict[str, str | None] = {}

# SVG-заглушки по категории (data URI) — последний рубеж, чтобы ни один товар не был без картинки
_PLACEHOLDER_SVG = {
    "cpu": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
        '<rect fill="#1a1f2e" width="400" height="300"/>'
        '<rect x="120" y="70" width="160" height="160" rx="12" fill="#2d3748" stroke="#63b3ed" stroke-width="3"/>'
        '<text x="200" y="160" text-anchor="middle" fill="#a0aec0" font-family="sans-serif" font-size="22">CPU</text>'
        '</svg>'
    ),
    "gpu": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
        '<rect fill="#1a1f2e" width="400" height="300"/>'
        '<rect x="80" y="100" width="240" height="100" rx="8" fill="#2d3748" stroke="#68d391" stroke-width="3"/>'
        '<text x="200" y="160" text-anchor="middle" fill="#a0aec0" font-family="sans-serif" font-size="22">GPU</text>'
        '</svg>'
    ),
    "ram": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
        '<rect fill="#1a1f2e" width="400" height="300"/>'
        '<rect x="60" y="120" width="280" height="60" rx="4" fill="#2d3748" stroke="#f6ad55" stroke-width="3"/>'
        '<text x="200" y="158" text-anchor="middle" fill="#a0aec0" font-family="sans-serif" font-size="20">RAM</text>'
        '</svg>'
    ),
    "motherboard": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
        '<rect fill="#1a1f2e" width="400" height="300"/>'
        '<rect x="90" y="50" width="220" height="200" rx="6" fill="#2d3748" stroke="#fc8181" stroke-width="3"/>'
        '<text x="200" y="160" text-anchor="middle" fill="#a0aec0" font-family="sans-serif" font-size="18">MB</text>'
        '</svg>'
    ),
    "ssd": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
        '<rect fill="#1a1f2e" width="400" height="300"/>'
        '<rect x="100" y="110" width="200" height="80" rx="6" fill="#2d3748" stroke="#b794f4" stroke-width="3"/>'
        '<text x="200" y="160" text-anchor="middle" fill="#a0aec0" font-family="sans-serif" font-size="22">SSD</text>'
        '</svg>'
    ),
    "hdd": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
        '<rect fill="#1a1f2e" width="400" height="300"/>'
        '<circle cx="200" cy="150" r="70" fill="#2d3748" stroke="#90cdf4" stroke-width="3"/>'
        '<text x="200" y="158" text-anchor="middle" fill="#a0aec0" font-family="sans-serif" font-size="22">HDD</text>'
        '</svg>'
    ),
    "psu": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
        '<rect fill="#1a1f2e" width="400" height="300"/>'
        '<rect x="110" y="90" width="180" height="120" rx="6" fill="#2d3748" stroke="#f687b3" stroke-width="3"/>'
        '<text x="200" y="160" text-anchor="middle" fill="#a0aec0" font-family="sans-serif" font-size="22">PSU</text>'
        '</svg>'
    ),
    "case": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
        '<rect fill="#1a1f2e" width="400" height="300"/>'
        '<rect x="130" y="40" width="140" height="220" rx="8" fill="#2d3748" stroke="#a0aec0" stroke-width="3"/>'
        '<text x="200" y="160" text-anchor="middle" fill="#a0aec0" font-family="sans-serif" font-size="18">CASE</text>'
        '</svg>'
    ),
    "cooler": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
        '<rect fill="#1a1f2e" width="400" height="300"/>'
        '<circle cx="200" cy="150" r="65" fill="#2d3748" stroke="#4fd1c5" stroke-width="3"/>'
        '<text x="200" y="158" text-anchor="middle" fill="#a0aec0" font-family="sans-serif" font-size="16">COOLER</text>'
        '</svg>'
    ),
}
_DEFAULT_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
    '<rect fill="#1a1f2e" width="400" height="300"/>'
    '<rect x="100" y="90" width="200" height="120" rx="10" fill="#2d3748" stroke="#718096" stroke-width="2"/>'
    '<text x="200" y="160" text-anchor="middle" fill="#a0aec0" font-family="sans-serif" font-size="18">PC PART</text>'
    '</svg>'
)


def placeholder_data_uri(category: str | None = None) -> str:
    svg = _PLACEHOLDER_SVG.get(category or "", _DEFAULT_SVG)
    # encode for data URI
    from urllib.parse import quote as q

    return "data:image/svg+xml," + q(svg)


def _clean_query(name: str) -> str:
    s = re.sub(r"[\(\)\[\]\{\}]", " ", name or "")
    s = re.sub(r"\s+", " ", s).strip()
    # обрезаем слишком длинные маркетинговые хвосты
    parts = s.split()
    if len(parts) > 8:
        s = " ".join(parts[:8])
    return s


async def search_wikimedia(client: httpx.AsyncClient, query: str) -> str | None:
    """Commons MediaWiki API — без ключа."""
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrlimit": "8",
        "gsrsearch": f"{query} filetype:bitmap",
        "prop": "imageinfo",
        "iiprop": "url|size|mime",
        "iiurlwidth": "640",
    }
    try:
        resp = await client.get("https://commons.wikimedia.org/w/api.php", params=params)
        if resp.status_code != 200:
            return None
        data = resp.json()
        pages = (data.get("query") or {}).get("pages") or []
        for page in pages:
            infos = page.get("imageinfo") or []
            for info in infos:
                mime = (info.get("mime") or "").lower()
                if not mime.startswith("image/"):
                    continue
                if mime in ("image/svg+xml", "image/gif"):
                    continue
                url = info.get("thumburl") or info.get("url")
                if url and url.startswith("http"):
                    return url
    except Exception:
        return None
    return None


async def search_openverse(client: httpx.AsyncClient, query: str) -> str | None:
    """Openverse API — открытые лицензии, без ключа."""
    params = {
        "q": query,
        "page_size": 5,
        "license_type": "commercial,modification",
        "extension": "jpg,png,webp",
    }
    try:
        resp = await client.get("https://api.openverse.org/v1/images/", params=params)
        if resp.status_code != 200:
            # старый хост
            resp = await client.get(
                "https://api.openverse.engineering/v1/images/", params=params
            )
        if resp.status_code != 200:
            return None
        data = resp.json()
        for item in data.get("results") or []:
            url = item.get("url") or item.get("thumbnail")
            if url and str(url).startswith("http"):
                return str(url)
    except Exception:
        return None
    return None


async def find_image_url(
    name: str,
    *,
    category: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Ищем картинку в интернете. Результат кэшируется."""
    q = _clean_query(name)
    if not q:
        return None
    cache_key = f"{category or ''}|{q.lower()}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20.0, headers=HEADERS, follow_redirects=True)

    assert client is not None
    url: str | None = None
    try:
        # 1) Wikimedia
        url = await search_wikimedia(client, q)
        # 2) Openverse с уточнением категории
        if not url:
            q2 = q
            cat_hint = {
                "cpu": "processor CPU",
                "gpu": "graphics card GPU",
                "ram": "DDR memory RAM",
                "motherboard": "motherboard",
                "ssd": "SSD NVMe",
                "hdd": "hard disk drive",
                "psu": "power supply PSU",
                "case": "PC case chassis",
                "cooler": "CPU cooler",
            }.get(category or "", "PC hardware")
            url = await search_openverse(client, f"{q2} {cat_hint}")
        if not url:
            url = await search_openverse(client, q)
    finally:
        if own_client:
            await client.aclose()

    _CACHE[cache_key] = url
    return url


async def find_image_or_placeholder(
    name: str,
    *,
    category: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Всегда возвращает URL или data:image/svg+xml."""
    url = await find_image_url(name, category=category, client=client)
    if url:
        return url
    return placeholder_data_uri(category)
