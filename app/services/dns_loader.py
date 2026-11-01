"""Загрузка реальных комплектующих из DNS через ReefAPI."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app import models

REEF_API_BASE = "https://api.reefapi.com"

CATEGORY_QUERIES: dict[str, list[str]] = {
    "cpu": [
        "процессор AMD Ryzen 5",
        "процессор AMD Ryzen 7",
        "процессор AMD Ryzen 9",
        "процессор Intel Core i5",
        "процессор Intel Core i7",
        "процессор Intel Core i9",
        "процессор Intel Core Ultra",
        "процессор AMD Ryzen 5 7600",
        "процессор AMD Ryzen 7 7800X3D",
        "процессор Intel Core i5 14600",
    ],
    "gpu": [
        "видеокарта RTX 4060",
        "видеокарта RTX 4070",
        "видеокарта RTX 4080",
        "видеокарта RTX 5070",
        "видеокарта RTX 5080",
        "видеокарта RX 7600",
        "видеокарта RX 7800",
        "видеокарта RX 7900",
        "видеокарта RTX 4060 Ti",
        "видеокарта RTX 4070 Ti",
    ],
    "motherboard": [
        "материнская плата B650",
        "материнская плата B760",
        "материнская плата X670",
        "материнская плата Z790",
        "материнская плата B850",
        "материнская плата AM5",
        "материнская плата LGA 1700",
    ],
    "ram": [
        "оперативная память DDR5 32ГБ",
        "оперативная память DDR5 16ГБ",
        "оперативная память DDR4 32ГБ",
        "оперативная память DDR5 6000",
        "оперативная память Kingston Fury",
        "оперативная память G.Skill",
    ],
    "ssd": [
        "SSD 1ТБ NVMe",
        "SSD 2ТБ NVMe",
        "SSD 500ГБ NVMe",
        "SSD Samsung 990",
        "SSD WD Black",
    ],
    "hdd": [
        "жесткий диск 2ТБ",
        "жесткий диск 4ТБ",
        "жесткий диск 8ТБ",
    ],
    "psu": [
        "блок питания 650Вт",
        "блок питания 750Вт",
        "блок питания 850Вт",
        "блок питания 80+ Gold",
    ],
    "case": [
        "корпус для ПК ATX",
        "корпус для ПК mATX",
        "корпус Mid-Tower",
        "корпус Lian Li",
    ],
    "cooler": [
        "кулер для процессора",
        "водяное охлаждение 240",
        "водяное охлаждение 360",
        "кулер Thermalright",
    ],
}

# Укороченный набор для экономного режима (мало кредитов)
ECONOMY_QUERIES: dict[str, list[str]] = {
    "cpu": ["процессор AMD Ryzen 5", "процессор Intel Core i5"],
    "gpu": ["видеокарта RTX 4060", "видеокарта RTX 4070"],
    "motherboard": ["материнская плата B650", "материнская плата B760"],
    "ram": ["оперативная память DDR5 32ГБ"],
    "ssd": ["SSD 1ТБ NVMe"],
    "hdd": ["жесткий диск 2ТБ"],
    "psu": ["блок питания 750Вт"],
    "case": ["корпус для ПК ATX"],
    "cooler": ["кулер для процессора"],
}


class CreditsExhaustedError(Exception):
    """Кредиты ReefAPI закончились или ключ отклонён."""


def get_api_key(override: str | None = None) -> str | None:
    if override and override.strip():
        return override.strip()
    key = os.getenv("REEFAPI_KEY")
    return key.strip() if key else None


async def check_credits(api_key: str) -> dict[str, Any] | None:
    """Проверка баланса кредитов. None если endpoint недоступен."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{REEF_API_BASE}/account/v1/credits",
                headers={"x-api-key": api_key},
            )
            if resp.status_code in (401, 403):
                raise CreditsExhaustedError("API-ключ отклонён или недействителен")
            if resp.status_code == 402:
                raise CreditsExhaustedError("Кредиты ReefAPI закончились")
            if resp.status_code >= 400:
                return None
            body = resp.json()
            data = body.get("data") if isinstance(body, dict) else body
            return data if isinstance(data, dict) else {"raw": data}
    except CreditsExhaustedError:
        raise
    except Exception:
        return None


async def reef_search(
    client: httpx.AsyncClient,
    api_key: str,
    query: str,
    page: int = 1,
) -> list[dict[str, Any]]:
    resp = await client.post(
        f"{REEF_API_BASE}/dns-shop/v1/search",
        headers={"x-api-key": api_key, "content-type": "application/json"},
        json={"query": query, "page": page},
    )
    if resp.status_code in (401, 403):
        raise CreditsExhaustedError("API-ключ отклонён")
    if resp.status_code == 402:
        raise CreditsExhaustedError("Кредиты ReefAPI закончились")

    # Иногда баланс в заголовке
    remaining = resp.headers.get("X-Credits-Remaining")
    if remaining is not None:
        try:
            if float(remaining) <= 0:
                raise CreditsExhaustedError("Кредиты ReefAPI закончились")
        except ValueError:
            pass

    resp.raise_for_status()
    body = resp.json()
    if not body.get("ok"):
        err = (body.get("error") or {}).get("message") or ""
        low = str(err).lower()
        if "credit" in low or "balance" in low or "quota" in low:
            raise CreditsExhaustedError("Кредиты ReefAPI закончились")
        return []
    data = body.get("data") or {}
    return data.get("results") or []


def _extract_brand(name: str) -> str | None:
    known = [
        "AMD", "Intel", "NVIDIA", "ASUS", "MSI", "Gigabyte", "ASRock",
        "Sapphire", "Palit", "GIGABYTE", "Kingston", "Corsair", "G.Skill",
        "Samsung", "WD", "Western Digital", "Seagate", "Crucial",
        "Deepcool", "DeepCool", "ID-Cooling", "be quiet", "Thermalright",
        "Arctic", "NZXT", "Fractal", "Lian Li", "Cooler Master", "Noctua",
        "ADATA", "XPG", "Montech", "Cougar", "PowerColor", "Zotac",
    ]
    upper = name.upper()
    for b in known:
        if b.upper() in upper:
            return b
    return None


def upsert_component_from_dns(
    db: Session,
    category: models.Category,
    store: models.Store,
    item: dict[str, Any],
) -> bool:
    external_id = item.get("product_id") or item.get("code")
    if not external_id:
        return False
    name = item.get("name") or ""
    if not name:
        return False

    existing_price = (
        db.query(models.Price)
        .filter(
            models.Price.store_id == store.id,
            models.Price.external_id == str(external_id),
        )
        .first()
    )

    specs = item.get("specs") or {}
    specs_json = json.dumps(specs, ensure_ascii=False) if isinstance(specs, dict) else None
    brand = item.get("brand") or _extract_brand(name)
    image = item.get("image")
    price_val = item.get("price")
    old_price = item.get("price_old")
    in_stock = bool(item.get("orderable")) or (item.get("avail_status") == "now")
    url = item.get("url")

    if existing_price:
        component = existing_price.component
        component.name = name
        component.brand = brand
        component.image_url = image or component.image_url
        if specs_json:
            component.specs = specs_json
        if price_val is not None:
            existing_price.price = float(price_val)
        if old_price is not None:
            existing_price.old_price = float(old_price)
        existing_price.in_stock = in_stock
        existing_price.product_url = url
        return False

    component = models.Component(
        category_id=category.id,
        name=name,
        brand=brand,
        model=None,
        description=item.get("short_specs"),
        image_url=image,
        specs=specs_json,
    )
    db.add(component)
    db.flush()
    db.add(
        models.Price(
            component_id=component.id,
            store_id=store.id,
            price=float(price_val) if price_val is not None else None,
            old_price=float(old_price) if old_price is not None else None,
            in_stock=in_stock,
            product_url=url,
            external_id=str(external_id),
        )
    )
    return True


async def load_dns_catalog(
    db: Session,
    max_per_query: int = 24,
    pages_per_query: int = 2,
    api_key: str | None = None,
    economy: bool = False,
) -> dict[str, Any]:
    key = get_api_key(api_key)
    if not key:
        raise RuntimeError("REEFAPI_KEY не задан")

    # Предпроверка кредитов (если API отдаёт)
    credits_info = await check_credits(key)

    categories = {c.name: c for c in db.query(models.Category).all()}
    store = db.query(models.Store).filter(models.Store.name == "DNS").first()
    if not store:
        store = models.Store(name="DNS", url="https://www.dns-shop.ru")
        db.add(store)
        db.flush()

    queries_map = ECONOMY_QUERIES if economy else CATEGORY_QUERIES
    pages = 1 if economy else pages_per_query
    per_page = 12 if economy else max_per_query

    added = 0
    updated_queries = 0
    errors = 0
    seen_ids: set[str] = set()
    stopped_reason: str | None = None

    jobs: list[tuple[str, str, int]] = []
    for cat_name, queries in queries_map.items():
        if cat_name not in categories:
            continue
        for query in queries:
            for page in range(1, pages + 1):
                jobs.append((cat_name, query, page))

    semaphore = asyncio.Semaphore(2 if economy else 3)

    async with httpx.AsyncClient(timeout=90.0) as client:

        async def fetch_one(cat_name: str, query: str, page: int):
            async with semaphore:
                results = await reef_search(client, key, query, page=page)
                return cat_name, results

        batch_size = 6
        for i in range(0, len(jobs), batch_size):
            batch = jobs[i : i + batch_size]
            try:
                outcomes = await asyncio.gather(*[fetch_one(c, q, p) for c, q, p in batch])
            except CreditsExhaustedError as e:
                stopped_reason = str(e)
                break
            except Exception:
                errors += len(batch)
                continue

            for cat_name, results in outcomes:
                if not results:
                    errors += 1
                    continue
                updated_queries += 1
                category = categories[cat_name]
                count = 0
                for item in results:
                    if count >= per_page:
                        break
                    pid = str(item.get("product_id") or item.get("code") or "")
                    if not pid or pid in seen_ids:
                        continue
                    seen_ids.add(pid)
                    if upsert_component_from_dns(db, category, store, item):
                        added += 1
                    count += 1
            db.commit()

    return {
        "components_added": added,
        "queries_ok": updated_queries,
        "errors": errors,
        "unique_seen": len(seen_ids),
        "economy": economy,
        "stopped_reason": stopped_reason,
        "credits": credits_info,
    }
