"""Загрузка реальных комплектующих из DNS через ReefAPI (расширенный каталог)."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app import models

REEF_API_BASE = "https://api.reefapi.com"

# Много запросов + несколько страниц → существенно больше товаров
CATEGORY_QUERIES: dict[str, list[str]] = {
    "cpu": [
        "процессор AMD Ryzen 5",
        "процессор AMD Ryzen 7",
        "процессор AMD Ryzen 9",
        "процессор AMD Ryzen 3",
        "процессор Intel Core i3",
        "процессор Intel Core i5",
        "процессор Intel Core i7",
        "процессор Intel Core i9",
        "процессор Intel Core Ultra",
        "процессор AMD Ryzen 5 7600",
        "процессор AMD Ryzen 7 7800X3D",
        "процессор AMD Ryzen 5 9600",
        "процессор Intel Core i5 14600",
        "процессор Intel Core i7 14700",
    ],
    "gpu": [
        "видеокарта RTX 4060",
        "видеокарта RTX 4060 Ti",
        "видеокарта RTX 4070",
        "видеокарта RTX 4070 Ti",
        "видеокарта RTX 4080",
        "видеокарта RTX 4090",
        "видеокарта RTX 5060",
        "видеокарта RTX 5070",
        "видеокарта RTX 5080",
        "видеокарта RX 7600",
        "видеокарта RX 7700",
        "видеокарта RX 7800",
        "видеокарта RX 7900",
        "видеокарта RTX 3050",
        "видеокарта GTX 1650",
        "видеокарта Arc A770",
    ],
    "motherboard": [
        "материнская плата B650",
        "материнская плата B550",
        "материнская плата X670",
        "материнская плата B760",
        "материнская плата Z790",
        "материнская плата H610",
        "материнская плата B850",
        "материнская плата X870",
        "материнская плата AM5",
        "материнская плата LGA 1700",
        "материнская плата AM4",
    ],
    "ram": [
        "оперативная память DDR5 32ГБ",
        "оперативная память DDR5 16ГБ",
        "оперативная память DDR5 64ГБ",
        "оперативная память DDR4 32ГБ",
        "оперативная память DDR4 16ГБ",
        "оперативная память DDR5 6000",
        "оперативная память Kingston Fury",
        "оперативная память G.Skill",
        "оперативная память Corsair",
        "оперативная память ADATA XPG",
    ],
    "ssd": [
        "SSD 1ТБ NVMe",
        "SSD 2ТБ NVMe",
        "SSD 500ГБ NVMe",
        "SSD 4ТБ NVMe",
        "SSD Samsung 990",
        "SSD WD Black",
        "SSD Kingston NV2",
        "SSD Crucial",
        "SSD 1ТБ SATA",
    ],
    "hdd": [
        "жесткий диск 1ТБ",
        "жесткий диск 2ТБ",
        "жесткий диск 4ТБ",
        "жесткий диск 6ТБ",
        "жесткий диск 8ТБ",
        "жесткий диск Seagate",
        "жесткий диск WD",
    ],
    "psu": [
        "блок питания 550Вт",
        "блок питания 650Вт",
        "блок питания 750Вт",
        "блок питания 850Вт",
        "блок питания 1000Вт",
        "блок питания 80+ Gold",
        "блок питания 80+ Bronze",
        "блок питания modular",
    ],
    "case": [
        "корпус для ПК ATX",
        "корпус для ПК mATX",
        "корпус Mini-ITX",
        "корпус Mid-Tower",
        "корпус с окном",
        "корпус Fractal",
        "корпус Lian Li",
        "корпус Deepcool",
        "корпус Montech",
    ],
    "cooler": [
        "кулер для процессора",
        "башенный кулер",
        "водяное охлаждение 120",
        "водяное охлаждение 240",
        "водяное охлаждение 360",
        "кулер Deepcool",
        "кулер Noctua",
        "кулер Thermalright",
        "СВО 280",
    ],
}


def get_api_key(override: str | None = None) -> str | None:
    if override and override.strip():
        return override.strip()
    key = os.getenv("REEFAPI_KEY")
    return key.strip() if key else None


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
    resp.raise_for_status()
    body = resp.json()
    if not body.get("ok"):
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
        "Gainward", "Inno3D", "PNY", "TeamGroup", "Patriot",
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
    if isinstance(specs, dict):
        specs_json = json.dumps(specs, ensure_ascii=False)
    else:
        specs_json = None

    brand = item.get("brand") or _extract_brand(name)
    image = item.get("image")
    price_val = item.get("price")
    old_price = item.get("price_old")
    # цена может быть даже если orderable=false — сохраняем как последнюю известную
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

    price = models.Price(
        component_id=component.id,
        store_id=store.id,
        price=float(price_val) if price_val is not None else None,
        old_price=float(old_price) if old_price is not None else None,
        in_stock=in_stock,
        product_url=url,
        external_id=str(external_id),
    )
    db.add(price)
    return True


async def load_dns_catalog(
    db: Session,
    max_per_query: int = 24,
    pages_per_query: int = 2,
    api_key: str | None = None,
) -> dict[str, int]:
    key = get_api_key(api_key)
    if not key:
        raise RuntimeError("REEFAPI_KEY не задан")

    categories = {c.name: c for c in db.query(models.Category).all()}
    store = db.query(models.Store).filter(models.Store.name == "DNS").first()
    if not store:
        store = models.Store(name="DNS", url="https://www.dns-shop.ru")
        db.add(store)
        db.flush()

    added = 0
    updated_queries = 0
    errors = 0
    seen_ids: set[str] = set()

    # собираем все задачи
    jobs: list[tuple[str, str, int]] = []
    for cat_name, queries in CATEGORY_QUERIES.items():
        if cat_name not in categories:
            continue
        for query in queries:
            for page in range(1, pages_per_query + 1):
                jobs.append((cat_name, query, page))

    semaphore = asyncio.Semaphore(3)  # не более 3 параллельных запросов

    async with httpx.AsyncClient(timeout=90.0) as client:

        async def fetch_one(cat_name: str, query: str, page: int) -> tuple[str, list[dict]]:
            async with semaphore:
                try:
                    results = await reef_search(client, key, query, page=page)
                    return cat_name, results
                except Exception:
                    return cat_name, []

        # батчами, чтобы не держать всё в памяти и коммитить периодически
        batch_size = 8
        for i in range(0, len(jobs), batch_size):
            batch = jobs[i : i + batch_size]
            outcomes = await asyncio.gather(*[fetch_one(c, q, p) for c, q, p in batch])
            for cat_name, results in outcomes:
                if not results:
                    errors += 1
                    continue
                updated_queries += 1
                category = categories[cat_name]
                count = 0
                for item in results:
                    if count >= max_per_query:
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
    }
