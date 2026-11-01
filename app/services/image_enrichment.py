"""
Быстрый поиск фото комплектующих.
Параллельный race источников, короткий таймаут на источник (~4с),
запросы заточены под hardware product photo.
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
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

_CACHE: dict[str, str | None] = {}
ImageStatus = Literal["ok", "timeout", "not_found", "error"]

# чёрный список доменов/паттернов (не фото товара)
_BAD_HOST_PARTS = (
    "meme", "reddit", "imgur.com/a/", "tiktok", "youtube", "facebook",
    "pinterest", "wikimedia.org/wikipedia/commons/thumb/archive",
)
_BAD_QUERY_HINTS = ("cartoon", "meme", "fanart", "cosplay", "lego")

_PLACEHOLDER_SVG = {
    k: (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">'
        f'<rect fill="#1a1f2e" width="400" height="300"/>'
        f'<text x="200" y="160" text-anchor="middle" fill="#a0aec0" '
        f'font-family="sans-serif" font-size="22">{k.upper()}</text></svg>'
    )
    for k in ("cpu", "gpu", "ram", "motherboard", "ssd", "hdd", "psu", "case", "cooler")
}
_DEFAULT_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">'
    '<rect fill="#1a1f2e" width="400" height="300"/>'
    '<text x="200" y="160" text-anchor="middle" fill="#a0aec0" '
    'font-family="sans-serif" font-size="18">PC PART</text></svg>'
)

CAT_HINT = {
    "cpu": "CPU processor box product photo",
    "gpu": "graphics card GPU product photo",
    "ram": "DDR RAM memory module product photo",
    "motherboard": "motherboard PCB product photo",
    "ssd": "SSD NVMe drive product photo",
    "hdd": "hard disk drive HDD product photo",
    "psu": "PC power supply PSU product photo",
    "case": "PC computer case chassis product photo",
    "cooler": "CPU cooler product photo",
}


def is_placeholder_url(url: str | None) -> bool:
    if not url:
        return True
    u = str(url).strip().lower()
    return (not u) or u.startswith("data:")


def placeholder_data_uri(category: str | None = None) -> str:
    svg = _PLACEHOLDER_SVG.get(category or "", _DEFAULT_SVG)
    return "data:image/svg+xml," + quote(svg)


def _clean_query(name: str) -> str:
    s = re.sub(r"[\(\)\[\]\{\}]", " ", name or "")
    s = re.sub(r"\s+", " ", s).strip()
    parts = s.split()
    if len(parts) > 10:
        s = " ".join(parts[:10])
    return s


def _ok_url(url: str | None) -> bool:
    if not url or not str(url).startswith("http"):
        return False
    low = str(url).lower()
    if low.endswith(".svg") or "svg+xml" in low:
        return False
    if any(b in low for b in _BAD_HOST_PARTS):
        return False
    return True


def _google_creds(api_key: str | None = None, cx: str | None = None):
    key = (api_key or os.getenv("GOOGLE_CSE_KEY") or "").strip() or None
    eng = (cx or os.getenv("GOOGLE_CSE_CX") or "").strip() or None
    return key, eng


async def search_google_cse(client, query, *, api_key=None, cx=None) -> str | None:
    key, eng = _google_creds(api_key, cx)
    if not key or not eng:
        return None
    try:
        resp = await client.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": key,
                "cx": eng,
                "q": query,
                "searchType": "image",
                "num": 5,
                "safe": "active",
                "imgSize": "medium",
                "imgType": "photo",
            },
            timeout=4.0,
        )
        if resp.status_code != 200:
            return None
        for item in (resp.json().get("items") or []):
            for candidate in (
                (item.get("image") or {}).get("thumbnailLink"),
                item.get("link"),
            ):
                if _ok_url(candidate):
                    return str(candidate)
    except Exception:
        return None
    return None


async def search_duckduckgo_images(client, query) -> str | None:
    try:
        r = await client.get(
            "https://duckduckgo.com/",
            params={"q": query},
            headers={**HEADERS, "Accept": "text/html"},
            timeout=4.0,
        )
        if r.status_code != 200:
            return None
        m = re.search(r"vqd=([\d-]+)", r.text) or re.search(r'vqd="([\d-]+)"', r.text)
        if not m:
            return None
        r2 = await client.get(
            "https://duckduckgo.com/i.js",
            params={"l": "ru-ru", "o": "json", "q": query, "vqd": m.group(1), "f": ",,,", "p": "1"},
            headers={**HEADERS, "Accept": "application/json", "Referer": "https://duckduckgo.com/"},
            timeout=4.0,
        )
        if r2.status_code != 200:
            return None
        for item in (r2.json().get("results") or []):
            for key in ("thumbnail", "image"):
                if _ok_url(item.get(key)):
                    return str(item[key])
    except Exception:
        return None
    return None


async def search_bing_images(client, query) -> str | None:
    try:
        r = await client.get(
            "https://www.bing.com/images/search",
            params={"q": query, "form": "HDRSC2", "first": "1", "qft": '+filterui:photo-photo'},
            headers={**HEADERS, "Accept": "text/html"},
            timeout=4.5,
        )
        if r.status_code != 200:
            return None
        html = r.text
        for pattern in (
            r'"murl"\s*:\s*"(https?://[^"\\]+)"',
            r'"turl"\s*:\s*"(https?://[^"\\]+)"',
        ):
            for m in re.finditer(pattern, html):
                url = m.group(1).replace("\\/", "/")
                if _ok_url(url):
                    return url
    except Exception:
        return None
    return None


async def search_wikimedia(client, query) -> str | None:
    try:
        resp = await client.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "generator": "search",
                "gsrnamespace": "6",
                "gsrlimit": "6",
                "gsrsearch": f"{query} filetype:bitmap",
                "prop": "imageinfo",
                "iiprop": "url|mime",
                "iiurlwidth": "640",
            },
            timeout=4.0,
        )
        if resp.status_code != 200:
            return None
        for page in ((resp.json().get("query") or {}).get("pages") or []):
            for info in page.get("imageinfo") or []:
                mime = (info.get("mime") or "").lower()
                if not mime.startswith("image/") or "svg" in mime:
                    continue
                url = info.get("thumburl") or info.get("url")
                if _ok_url(url):
                    return url
    except Exception:
        return None
    return None


async def find_image_url(
    name: str,
    *,
    category: str | None = None,
    client: httpx.AsyncClient | None = None,
    timeout_sec: float = 12.0,
    google_api_key: str | None = None,
    google_cx: str | None = None,
) -> tuple[str | None, ImageStatus, str | None]:
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

    timeout_sec = max(3.0, min(30.0, float(timeout_sec or 12)))
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=5.0, headers=HEADERS, follow_redirects=True)
    assert client is not None

    hint = CAT_HINT.get(category or "", "PC hardware product photo")
    # кавычки вокруг модели + жёсткий контекст товара
    q_hw = f'"{q}" {hint}'

    async def _one(label: str, coro):
        try:
            url = await coro
            if url:
                return url, label
        except Exception:
            pass
        return None, label

    async def _race() -> tuple[str | None, str | None]:
        tasks = [
            asyncio.create_task(_one("duckduckgo", search_duckduckgo_images(client, q_hw))),
            asyncio.create_task(_one("bing", search_bing_images(client, q_hw))),
            asyncio.create_task(_one("wikimedia", search_wikimedia(client, q))),
        ]
        if google_api_key and google_cx:
            tasks.insert(
                0,
                asyncio.create_task(
                    _one("google", search_google_cse(client, q_hw, api_key=google_api_key, cx=google_cx))
                ),
            )
        try:
            for fut in asyncio.as_completed(tasks, timeout=timeout_sec):
                try:
                    url, label = await fut
                except Exception:
                    continue
                if url:
                    for t in tasks:
                        t.cancel()
                    return url, label
        except asyncio.TimeoutError:
            for t in tasks:
                t.cancel()
            return None, None
        return None, None

    try:
        url, source = await _race()
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

        host = f"{source}/{urlparse(url).netloc}" if source else urlparse(url).netloc
        return url, "ok", host
    return None, "not_found", None


async def find_image_or_placeholder(
    name: str,
    *,
    category: str | None = None,
    client: httpx.AsyncClient | None = None,
    timeout_sec: float = 12.0,
    google_api_key: str | None = None,
    google_cx: str | None = None,
) -> str:
    url, _, _ = await find_image_url(
        name,
        category=category,
        client=client,
        timeout_sec=timeout_sec,
        google_api_key=google_api_key,
        google_cx=google_cx,
    )
    return url or placeholder_data_uri(category)
