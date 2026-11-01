"""
Поиск картинок:
1) Google Custom Search (Images) — если заданы API key + CX (официальный API)
2) DuckDuckGo Images — первая превьюшка без ключа
3) Wikimedia Commons
4) Openverse

Прямой парсинг google.com/imghp не используем (ToS Google + CAPTCHA).
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Literal
from urllib.parse import quote, unquote

import httpx

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PCComparator/0.4.6; "
        "+https://github.com/DoctorGreeb/pc-component-comparator)"
    ),
    "Accept": "application/json, text/html, */*",
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


def _google_creds(
    api_key: str | None = None, cx: str | None = None
) -> tuple[str | None, str | None]:
    key = (api_key or os.getenv("GOOGLE_CSE_KEY") or "").strip() or None
    eng = (cx or os.getenv("GOOGLE_CSE_CX") or "").strip() or None
    return key, eng


async def search_google_cse(
    client: httpx.AsyncClient,
    query: str,
    *,
    api_key: str | None = None,
    cx: str | None = None,
) -> str | None:
    """Google Programmable Search — searchType=image, берём первый link."""
    key, eng = _google_creds(api_key, cx)
    if not key or not eng:
        return None
    params = {
        "key": key,
        "cx": eng,
        "q": query,
        "searchType": "image",
        "num": 3,
        "safe": "active",
        "imgSize": "medium",
        "imgType": "photo",
    }
    try:
        resp = await client.get("https://www.googleapis.com/customsearch/v1", params=params)
        if resp.status_code != 200:
            return None
        data = resp.json()
        for item in data.get("items") or []:
            # link — оригинал, image.thumbnailLink — превью
            link = item.get("link")
            thumb = (item.get("image") or {}).get("thumbnailLink")
            for candidate in (thumb, link):
                if candidate and str(candidate).startswith("http"):
                    return str(candidate)
    except Exception:
        return None
    return None


async def search_duckduckgo_images(client: httpx.AsyncClient, query: str) -> str | None:
    """
    Первая превьюшка из выдачи DuckDuckGo Images (без API-ключа).
    Близкий UX к «первой картинке из поиска».
    """
    try:
        # 1) страница поиска — вытаскиваем vqd
        r = await client.get(
            "https://duckduckgo.com/",
            params={"q": query},
            headers={**HEADERS, "Accept": "text/html"},
        )
        if r.status_code != 200:
            return None
        html = r.text
        m = re.search(r"vqd=([\d-]+)", html)
        if not m:
            m = re.search(r"vqd=\"([\d-]+)\"", html)
        if not m:
            m = re.search(r"vqd':\s*'([\d-]+)'", html)
        if not m:
            return None
        vqd = m.group(1)

        # 2) JSON-лента картинок
        r2 = await client.get(
            "https://duckduckgo.com/i.js",
            params={
                "l": "ru-ru",
                "o": "json",
                "q": query,
                "vqd": vqd,
                "f": ",,,",
                "p": "1",
            },
            headers={**HEADERS, "Accept": "application/json", "Referer": "https://duckduckgo.com/"},
        )
        if r2.status_code != 200:
            return None
        data = r2.json()
        results = data.get("results") or []
        for item in results:
            # thumbnail — превью, image — полное
            for key in ("thumbnail", "image"):
                url = item.get(key)
                if url and str(url).startswith("http"):
                    return str(url)
    except Exception:
        return None
    return None


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
    google_api_key: str | None = None,
    google_cx: str | None = None,
) -> tuple[str | None, ImageStatus, str | None]:
    """
    Ищем картинку. Возвращает (url, status, host).
    Порядок: Google CSE → DuckDuckGo (первая превью) → Wikimedia → Openverse.
    """
    q = _clean_query(name)
    if not q:
        return None, "not_found", None
    cache_key = f"{category or ''}|{q.lower()}|{bool(google_api_key)}"
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
            timeout=min(timeout_sec, 25.0),
            headers=HEADERS,
            follow_redirects=True,
        )

    assert client is not None

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
    q_full = f"{q} {cat_hint}"

    async def _search() -> tuple[str | None, str | None]:
        # 1) Google Custom Search Images (если ключ)
        url = await search_google_cse(
            client, q_full, api_key=google_api_key, cx=google_cx
        )
        if url:
            return url, "google"

        # 2) DuckDuckGo — первая превьюшка без ключа
        url = await search_duckduckgo_images(client, q_full)
        if url:
            return url, "duckduckgo"
        url = await search_duckduckgo_images(client, q)
        if url:
            return url, "duckduckgo"

        # 3) Wikimedia
        url = await search_wikimedia(client, q)
        if url:
            return url, "wikimedia"

        # 4) Openverse
        url = await search_openverse(client, q_full)
        if url:
            return url, "openverse"
        url = await search_openverse(client, q)
        if url:
            return url, "openverse"
        return None, None

    try:
        url, source = await asyncio.wait_for(_search(), timeout=timeout_sec)
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

        host = urlparse(url).netloc or source or "web"
        if source:
            host = f"{source}/{host}"
        return url, "ok", host
    return None, "not_found", None


async def find_image_or_placeholder(
    name: str,
    *,
    category: str | None = None,
    client: httpx.AsyncClient | None = None,
    timeout_sec: float = 15.0,
    google_api_key: str | None = None,
    google_cx: str | None = None,
) -> str:
    url, _status, _host = await find_image_url(
        name,
        category=category,
        client=client,
        timeout_sec=timeout_sec,
        google_api_key=google_api_key,
        google_cx=google_cx,
    )
    if url:
        return url
    return placeholder_data_uri(category)
