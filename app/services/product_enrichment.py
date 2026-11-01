"""
Обогащение карточек товара: описание, обзоры и автоматический поиск характеристик.
"""
from __future__ import annotations

import asyncio
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
    value = re.sub(r"(?s)<[^>]+", " ", value)
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
            for match in re.finditer(r'(?is)<a\b(?=[^>]*class="[^"]*result__a)([^>]*)>(.*?)</a>', html):
                href_match = re.search(r'href="([^"]+)"', match.group(1))
                if not href_match:
                    continue
                href = unescape(href_match.group(1))
                redirect = re.search(r"[?&]uddg=([^&]+)", href)
                if redirect:
                    href = unquote(redirect.group(1))
                if href.startswith("//"):
                    href = "https:" + href
                if not href.startswith("http"):
                    continue
                vicinity = html[max(0, match.start() - 500):min(len(html), match.end() + 1800)]
                snippet_match = re.search(r'(?is)class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|td|div)', vicinity)
                results.append({
                    "title": _plain_html(match.group(2)),
                    "snippet": _plain_html(snippet_match.group(1))[:1000] if snippet_match else "",
                    "url": href,
                })
    except Exception:
        pass
    try:
        response = await client.get("https://www.bing.com/search", params={"q": query})
        if response.status_code == 200:
            for block in re.findall(r'(?is)<li[^>]+class="[^"]*b_algo[^"]*"[^>]*>.*?</li>', response.text):
                match = re.search(r'(?is)<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
                if match:
                    snippet_match = re.search(r'(?is)<p[^>]*>(.*?)</p>', block)
                    results.append({
                        "title": _plain_html(match.group(2)),
                        "snippet": _plain_html(snippet_match.group(1)) if snippet_match else "",
                        "url": unescape(match.group(1)),
                    })
    except Exception:
        pass
    return results


def _model_codes(*values: str | None) -> set[str]:
    text = " ".join(v or "" for v in values).upper()
    codes = re.findall(r"(?<![A-Z0-9])[A-Z]{1,8}[- ]?[A-Z0-9]{2,}(?:[- ][A-Z0-9]{1,8})?(?![A-Z0-9])", text)
    return {normalized for code in codes if any(ch.isdigit() for ch in code) for normalized in [re.sub(r"[^A-Z0-9]", "", code)] if len(normalized) >= 4}


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


<<<<<<< HEAD
# Common PC / store characteristic labels (RU + EN). Order does not matter;
# longer labels are preferred when building the regex.
_KNOWN_SPEC_LABELS = [
    # CPU / motherboard
    "Сокет", "Socket", "Чипсет", "Chipset", "Количество ядер", "Общее количество ядер",
    "Количество потоков", "Максимальная частота", "Базовая частота", "Частота процессора",
    "Тепловыделение", "TDP", "Техпроцесс", "Кэш L3", "Интегрированная графика",
    "Тип памяти", "Memory Type", "Поддерживаемая память", "Максимальный объем памяти",
    "Количество слотов памяти", "Форм-фактор", "Form Factor", "Версия PCI Express",
    # RAM / storage
    "Суммарный объем", "Объем", "Capacity", "Тактовая частота", "Frequency",
    "Тайминги", "Латентность", "CL", "Напряжение", "Модулей в комплекте",
    "Интерфейс", "Interface", "Тип накопителя", "Скорость чтения", "Скорость записи",
    "Скорость вращения", "RPM", "Форм-фактор накопителя",
    # GPU
    "Графический процессор", "Графический чип", "Объем видеопамяти", "Тип видеопамяти",
    "Шина памяти", "Частота ядра", "Рекомендуемая мощность БП", "Разъемы питания",
    "Длина видеокарты", "Количество вентиляторов",
    # Cooler / case / PSU
    "Макс. скорость вращения, об/мин", "Макс. воздушный поток, CFM",
    "Макс. уровень шума, дБ", "Диаметр вентилятора, мм", "Тип подшипника",
    "Коннектор питания", "Высота кулера", "Совместимые сокеты", "Тип охлаждения",
    "Мощность", "Wattage", "Сертификат 80 PLUS", "Модульность",
    "Поддержка материнских плат", "Отсеки 2.5", "Отсеки 3.5",
    # Generic
    "Размеры, мм", "Габариты", "Высота, мм", "Ширина, мм", "Глубина, мм",
    "Вес", "Цвет", "Подсветка", "Особенности", "Гарантия", "Страна-изготовитель",
    "Артикул", "Модель", "Производитель", "Бренд", "Тип",
]

_NOISE_KEYS = {
    "купить", "цена", "наличие", "отзыв", "рейтинг", "доставка", "в корзину",
    "добавить", "сравнить", "артикул продавца", "id", "sku", "ean", "barcode",
    "фото", "изображение", "описание", "подробнее", "share", "cookie",
}


def _is_good_spec_pair(key: str, value: str) -> bool:
    key = (key or "").strip()
    value = (value or "").strip()
    if not key or not value:
        return False
    if len(key) < 2 or len(key) > 80:
        return False
    if len(value) < 1 or len(value) > 220:
        return False
    if key.lower() == value.lower():
        return False
    kl = key.lower()
    if any(n in kl for n in _NOISE_KEYS):
        return False
    # Reject pure navigation / UI crumbs
    if re.search(r"https?://|www\.|\.html|\.php", value, re.I):
        return False
    if re.fullmatch(r"[\d\s.,]+", key):
        return False
    return True


def _spec_pairs_from_text(text: str) -> dict[str, str]:
    """Extract key/value specs from plain text or search snippets."""
    text = unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    specs: dict[str, str] = {}
<<<<<<< HEAD

    # 1) Known labels even without strict separators (common in SERP snippets)
    label_pattern = "|".join(re.escape(label) for label in sorted(_KNOWN_SPEC_LABELS, key=len, reverse=True))
    pattern = (
        rf"(?i)(?<![А-ЯЁA-Zа-яёa-z0-9])(?P<key>{label_pattern})\s*"
        rf"[:\-–—]?\s*(?P<value>.*?)(?=\s+(?:{label_pattern})(?:\s|[:\-–—])|$)"
    )
=======
    labels = [
        "Макс. скорость вращения, об/мин", "Макс. воздушный поток, CFM",
        "Макс. уровень шума, дБ", "Диаметр вентилятора, мм", "Количество вентиляторов",
        "Коннектор питания", "Тип подшипника", "Страна-изготовитель", "Количество в упаковке, шт",
        "Размеры, мм", "Особенности", "Подсветка", "Артикул", "Высота, мм", "Ширина, мм",
        "Глубина, мм", "Цвет", "Тип",
    ]
    label_pattern = "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    # Extract known field names up to the next known field, even when snippets omit punctuation.
    pattern = rf"(?i)(?<![А-ЯЁA-Zа-яёa-z0-9])(?P<key>{label_pattern})\s*:?\s*(?P<value>.*?)(?=\s+(?:{label_pattern})(?:\s|:)|$)"
>>>>>>> b1b5f92 (Correct whitespace regex escaping in snippet parser)
    for match in re.finditer(pattern, text):
        key = match.group("key").strip()
        value = match.group("value").strip(" .;,:-–—|")
        if _is_good_spec_pair(key, value):
            specs[key] = value

    # 2) Generic "Key: Value" / "Key — Value" / "Key - Value"
    for key, value in re.findall(
<<<<<<< HEAD
        r"([А-ЯЁA-Z][А-ЯЁA-Zа-яёa-z0-9 /(),.%+-]{1,50}?)\s*[:\-–—]\s*([^:;\n|•·]{1,100})",
=======
        r"([А-ЯЁA-Z][А-ЯЁA-Zа-яёa-z0-9 /(),.-]{2,45})\s*:\s*([^:;|]{1,80})",
>>>>>>> b1b5f92 (Correct whitespace regex escaping in snippet parser)
        text,
    ):
        key, value = key.strip(" .:-–—"), value.strip(" .;,:-–—|")
        if _is_good_spec_pair(key, value):
            specs.setdefault(key, value)

    # 3) Bullet-style "• Key Value" where value starts with digit/unit
    for key, value in re.findall(
        r"[•·▪▫]\s*([А-ЯЁA-Za-z][^:•·|]{2,40}?)\s+(\d[\d\s.,/x×*]*(?:\s*[A-Za-zА-Яа-яё%]+)?)",
        text,
    ):
        key, value = key.strip(), (value or "").strip()
        if value and _is_good_spec_pair(key, value):
            specs.setdefault(key, value)

    return specs


def _extract_div_spec_pairs(page: str) -> dict[str, str]:
    """Div/span based characteristics used by many RU stores (DNS, Citilink, Ozon…)."""
    specs: dict[str, str] = {}
    # Pairs of adjacent elements whose class hints at "name/title" + "value"
    pair_re = re.compile(
        r"(?is)"
        r"<(?:div|span|li|dt|td|th)[^>]*class=\"[^\"]*(?:spec|param|characteristic|property|attr|feature)"
        r"[^\"]*(?:name|title|label|key)[^\"]*\"[^>]*>(.*?)</(?:div|span|li|dt|td|th)>\s*"
        r"<(?:div|span|li|dd|td|th)[^>]*class=\"[^\"]*(?:spec|param|characteristic|property|attr|feature)"
        r"[^\"]*(?:value|val|data|text)[^\"]*\"[^>]*>(.*?)</(?:div|span|li|dd|td|th)>"
    )
    for key_html, val_html in pair_re.findall(page):
        key, value = _plain_html(key_html)[:100], _plain_html(val_html)[:300]
        if _is_good_spec_pair(key, value):
            specs.setdefault(key, value)

    # data-title / data-name attributes with nearby text value
    for key, value in re.findall(
        r'(?is)data-(?:title|name|label)=["\']([^"\']{2,60})["\'][^>]*>([^<]{1,120})<',
        page,
    ):
        key, value = _plain_html(key)[:100], _plain_html(value)[:300]
        if _is_good_spec_pair(key, value):
            specs.setdefault(key, value)

    # Microdata / itemprop
    for key, value in re.findall(
        r'(?is)itemprop=["\']([^"\']+)["\'][^>]*content=["\']([^"\']+)["\']',
        page,
    ):
        if key.lower() not in {"name", "image", "url", "sku", "price", "availability"}:
            if _is_good_spec_pair(key, value):
                specs.setdefault(key[:100], value[:300])

    return specs


def _walk_json_for_specs(node: Any, specs: dict[str, str], depth: int = 0) -> None:
    if depth > 12:
        return
    if isinstance(node, dict):
        # Schema.org Product additionalProperty
        props = node.get("additionalProperty") or node.get("additionalProperties")
        if isinstance(props, dict):
            props = [props]
        if isinstance(props, list):
            for prop in props:
                if isinstance(prop, dict):
                    key = prop.get("name") or prop.get("propertyID") or prop.get("key") or prop.get("title")
                    value = prop.get("value") or prop.get("valueReference") or prop.get("displayValue")
                    if key and value is not None and not isinstance(value, (dict, list)):
                        k, v = str(key)[:100].strip(), str(value)[:300].strip()
                        if _is_good_spec_pair(k, v):
                            specs.setdefault(k, v)

        # Generic key/value shaped objects (DNS/Citilink hydration etc.)
        key = node.get("name") or node.get("key") or node.get("title") or node.get("label") or node.get("characteristic")
        value = node.get("value") or node.get("displayValue") or node.get("val") or node.get("text")
        if key and value is not None and not isinstance(value, (dict, list)):
            k, v = str(key)[:100].strip(), str(value)[:300].strip()
            # Prefer objects that look like product attributes
            if _is_good_spec_pair(k, v) and (
                "spec" in str(node.get("type", "")).lower()
                or "char" in str(node.get("type", "")).lower()
                or node.get("unit") is not None
                or any(x in k.lower() for x in (
                    "сокет", "socket", "tdp", "ядер", "памят", "частот", "мощност",
                    "объем", "интерфейс", "форм", "чипсет", "watt", "core",
                ))
            ):
                specs.setdefault(k, v)

        # Nested dicts that are flat characteristic maps
        for k, v in node.items():
            if isinstance(k, str) and not isinstance(v, (dict, list)) and v is not None:
                if k.lower() in {x.lower() for x in _KNOWN_SPEC_LABELS} or any(
                    word in k.lower() for word in (
                        "сокет", "socket", "tdp", "ядер", "памят", "частот", "мощност",
                        "объем", "интерфейс", "форм-фактор", "чипсет", "watt",
                    )
                ):
                    ks, vs = k[:100].strip(), str(v)[:300].strip()
                    if _is_good_spec_pair(ks, vs):
                        specs.setdefault(ks, vs)

        for v in node.values():
            if isinstance(v, (dict, list)):
                _walk_json_for_specs(v, specs, depth + 1)
    elif isinstance(node, list):
        for item in node[:400]:
            _walk_json_for_specs(item, specs, depth + 1)


def _extract_spec_rows(page: str) -> dict[str, str]:
    """Parse product HTML for characteristic tables / lists / embedded JSON."""
    specs: dict[str, str] = {}

    # Classic table rows
    for row in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", page):
        cells = re.findall(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>", row)
        if len(cells) >= 2:
            key, value = _plain_html(cells[0])[:100].strip(" :"), _plain_html(cells[1])[:300]
            if _is_good_spec_pair(key, value):
                specs[key] = value

    # Definition lists
    for key, value in re.findall(r"(?is)<dt\b[^>]*>(.*?)</dt>\s*<dd\b[^>]*>(.*?)</dd>", page):
        k, v = _plain_html(key)[:100], _plain_html(value)[:300]
        if _is_good_spec_pair(k, v):
            specs.setdefault(k, v)

    # Div-based layouts of major marketplaces
    for k, v in _extract_div_spec_pairs(page).items():
        specs.setdefault(k, v)

    # JSON-LD / hydration blobs inside <script>
    scripts = re.findall(r"(?is)<script[^>]*>(.*?)</script>", page)
    decoder = json.JSONDecoder()
    for raw in scripts:
        if len(raw) > 3_000_000:
            continue
        # Prefer scripts that mention characteristics / product
        low = raw[:2000].lower()
        if not any(x in low for x in ("characteristic", "spec", "additionalproperty", "product", "param", "attrs")):
            # Still try short JSON-LD blocks
            if "application/ld+json" not in low and len(raw) > 80_000:
                continue
        # Scan for multiple JSON objects in one script
        pos = 0
        while pos < len(raw):
            start_candidates = [i for i in (raw.find("{", pos), raw.find("[", pos)) if i >= 0]
            if not start_candidates:
                break
            start = min(start_candidates)
            try:
                data, end = decoder.raw_decode(raw[start:])
            except Exception:
                pos = start + 1
                continue
            _walk_json_for_specs(data, specs)
            pos = start + max(end, 1)
            if len(specs) >= 40:
                break

    # Last resort: plain-text pairs from stripped page (helps when markup is unusual)
    if len(specs) < 3:
        plain = _plain_html(page)
        # Limit size for regex performance
        for k, v in _spec_pairs_from_text(plain[:120_000]).items():
            specs.setdefault(k, v)

    return {k: v for k, v in specs.items() if k and v}


_PREFERRED_HOSTS = (
    "dns-shop.ru", "citilink.ru", "ozon.ru", "wildberries.ru", "mvideo.ru",
    "technopoint.ru", "regard.ru", "computeruniverse.ru", "pleer.ru",
    "amd.com", "intel.com", "nvidia.com", "asus.com", "msi.com", "gigabyte.com",
)


def _candidate_priority(url: str) -> int:
    host = (urlparse(url).netloc or "").lower().replace("www.", "")
    for i, preferred in enumerate(_PREFERRED_HOSTS):
        if preferred in host:
            return i
    return 100


async def search_specs_on_web(name: str, brand: str | None = None, model: str | None = None) -> dict[str, Any] | None:
    """Search snippets first, then open matching product pages and parse their spec data."""
    query = _clean_query(" ".join(x for x in (brand, model, name) if x))
    if not query:
        return None
    model_or_name = model or name
    queries = list(dict.fromkeys([
        f'"{model_or_name}" характеристики',
        f"{query} характеристики",
        f"{query} specs",
        f"site:dns-shop.ru {model_or_name}",
        f"site:citilink.ru {model_or_name}",
        f"site:ozon.ru/product {model_or_name}",
        f"site:regard.ru {model_or_name}",
    ]))
    headers = {
        "User-Agent": UA,
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    seen: set[str] = set()
    candidates: list[dict[str, str]] = []
    best_snippet: dict[str, Any] | None = None

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(12, connect=5),
        headers=headers,
        follow_redirects=True,
    ) as client:
        for search_query in queries:
            for result in await _search_results(client, search_query):
                url = result["url"]
                if url in seen:
                    continue
                blob = f"{result['title']} {result['snippet']}"
                if not _matches_product(blob, name, brand, model):
                    continue
                seen.add(url)
                candidates.append(result)
                snippet_specs = _spec_pairs_from_text(result["snippet"])
                if len(snippet_specs) >= 3:
                    return {
                        "specs": snippet_specs,
                        "source": "search_snippet",
                        "source_title": result["title"],
                        "source_url": url,
                    }
                if len(snippet_specs) >= 2 and (
                    best_snippet is None or len(snippet_specs) > len(best_snippet["specs"])
                ):
                    best_snippet = {
                        "specs": snippet_specs,
                        "source": "search_snippet",
                        "source_title": result["title"],
                        "source_url": url,
                    }
            if len(candidates) >= 24:
                break

        # Prefer known store / manufacturer pages
        candidates.sort(key=lambda r: _candidate_priority(r["url"]))

        semaphore = asyncio.Semaphore(6)

        async def inspect_candidate(result: dict[str, str]):
            async with semaphore:
                try:
                    response = await client.get(result["url"])
                    ctype = response.headers.get("content-type", "").lower()
                    if response.status_code != 200 or ("html" not in ctype and "text" not in ctype):
                        return None
                    specs = _extract_spec_rows(response.text)
                    if len(specs) >= 3:
                        return {
                            "specs": specs,
                            "source": "web_page",
                            "source_title": result["title"],
                            "source_url": str(response.url),
                        }
                    # Keep weaker page hits as fallback
                    if len(specs) >= 2:
                        return {
                            "specs": specs,
                            "source": "web_page_weak",
                            "source_title": result["title"],
                            "source_url": str(response.url),
                        }
                except Exception:
                    return None
            return None

        page_results = await asyncio.gather(*(inspect_candidate(item) for item in candidates[:18]))
        # Prefer full hits, then weak page hits
        weak = None
        for result in page_results:
            if not result:
                continue
            if result["source"] == "web_page":
                return result
            if weak is None:
                weak = result
        if weak:
            return weak
        if best_snippet:
            return best_snippet
=======
async def search_specs_on_web(name: str, brand: str | None = None, model: str | None = None) -> dict[str, Any] | None:
    """Placeholder until full module is restored — returns None so API stays up."""
>>>>>>> 0e479550dfb48bf9e2ac313679d208f33aaaf475
    return None


async def enrich_product_page(name: str, brand: str | None = None, model: str | None = None,
                              existing_description: str | None = None) -> dict[str, Any]:
    links = manufacturer_links(brand, name, model)
    description = (existing_description or "").strip()
    source, source_url = ("database", None) if description else (None, None)
    if len(description) < 60:
        result = await fetch_wikipedia_summary(name) or await fetch_ddg_abstract(name)
        if result:
            description, source, source_url = result["extract"], result.get("source"), result.get("url")
    return {
        "description": description or None, "description_source": source, "description_url": source_url,
        "manufacturer_home": links["manufacturer_home"], "manufacturer_model_url": links["manufacturer_model_search"],
        "web_search_url": links["web_search"], "reviews": [],
        "reviews_note": "Модуль характеристик временно в режиме восстановления.",
    }
