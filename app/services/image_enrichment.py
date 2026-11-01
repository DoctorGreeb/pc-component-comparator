"""
Поиск картинок без API-ключа:
1) Wikimedia Commons (MediaWiki API)
2) Openverse (Creative Commons / openverse.org)

Поддерживает лимит времени на один товар (timeout_sec).
"""
from __future__ import annotations

import asyncio
import re
from typing import Literal
from urllib.parse import quote

import httpx

HEADERS = {
    "User-Agent": "PCComparator/0.4.5 (https://github.com/DoctorGreeb/pc-component-comparator; contact via github)",
    "Accept": "application/json",
}

_CACHE: dict[str, str | None] = {}

ImageStatus = Literal["ok", "timeout", "not_found", "error"]

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
    return "data:image/svg+xml," + quote(svg)


def _clean_query(name: str) -> str:
    s = re.sub(r"[\(\)\[\]\{\}]", " ", name or "")
    s = re.sub(r"\s+", " ", s).strip()
    parts = s.split()
    if len(parts) > 8:
        s = " ".join(parts[:8])
    return s


async def search_wikimedia(client: httpx.AsyncClient, query: str) -> str | None:
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
            for info in page.get("imageinfo") or []:
                mime = (info.get("mime") or "").lower()
                if not mime.startswith("image/") or mime in ("image/svg+xml", "image/gif"):
                    continue
                url = info.get("thumburl") or info.get("url")
                if url and url.startswith("http"):
                    return url
    except Exception:
        return None
    return None


async def search_openverse(client: httpx.AsyncClient, query: str) -> str | None:
    params = {
        "q": query,
        "page_size": 5,
        "license_type": "commercial,modification",
        "extension": "jpg,png,webp",
    }
    try:
        resp = await client.get("https://api.openverse.org/v1/images/", params=params)
        if resp.status_code != 200:
            resp = await client.get("https://api.openverse.engineering/v1/images/", params=params)
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
    timeout_sec: float = 15.0,
) -> tuple[str | None, ImageStatus, str | None]:
    """
    Ищем картинку. Возвращает (url, status, host).
    status: ok | timeout | not_found | error
    """
    q = _clean_query(name)
    if not q:
        return None, "not_found", None
    cache_key = f"{category or ''}|{q.lower()}"
    if cache_key in _CACHE:
        cached = _CACHE[cache_key]
        if cached:
            from urllib.parse import urlparse

            return cached, "ok", urlparse(cached).netloc or "cache"
        return None, "not_found", None

    timeout_sec = max(1.0, min(99.0, float(timeout_sec or 15)))
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            timeout=min(timeout_sec, 20.0),
            headers=HEADERS,
            follow_redirects=True,
        )

    assert client is not None

    async def _search() -> str | None:
        url = await search_wikimedia(client, q)
        if url:
            return url
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
        url = await search_openverse(client, f"{q} {cat_hint}")
        if url:
            return url
        return await search_openverse(client, q)

    try:
        url = await asyncio.wait_for(_search(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        if own_client:
            await client.aclose()
        return None, "timeout", None
    except Exception:
        if own_client:
            await client.aclose()
        return None, "error", None
    finally:
        if own_client and not client.is_closed:
            try:
                await client.aclose()
            except Exception:
                pass

    _CACHE[cache_key] = url
    if url:
        from urllib.parse import urlparse

        return url, "ok", urlparse(url).netloc or "web"
    return None, "not_found", None


async def find_image_or_placeholder(
    name: str,
    *,
    category: str | None = None,
    client: httpx.AsyncClient | None = None,
    timeout_sec: float = 15.0,
) -> str:
    url, _status, _host = await find_image_url(
        name, category=category, client=client, timeout_sec=timeout_sec
    )
    if url:
        return url
    return placeholder_data_uri(category)
