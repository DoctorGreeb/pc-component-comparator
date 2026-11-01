"""
Загрузка реальных комплектующих из DNS через ReefAPI.
"""
from __future__ import annotations

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
        "процессор Intel Core i5",
        "процессор Intel Core i7",
    ],
    "gpu": [
        "видеокарта RTX 4060",
        "видеокарта RTX 4070",
        "видеокарта RTX 5070",
        "видеокарта RX 7600",
    ],
    "motherboard": [
        "материнская плата B650",
        "материнская плата B760",
        "материнская плата X670",
    ],
    "ram": [
        "оперативная память DDR5 32ГБ",
        "оперативная память DDR4 32ГБ",
        "оперативная память DDR5 16ГБ",
    ],
    "ssd": [
        "SSD 1ТБ NVMe",
        "SSD 2ТБ NVMe",
        "SSD 500ГБ NVMe",
    ],
    "hdd": [
        "жесткий диск 2ТБ",
        "жесткий диск 4ТБ",
    ],
    "psu": [
        "блок питания 650Вт",
        "блок питания 750Вт",
        "блок питания 850Вт",
    ],
    "case": [
        "корпус для ПК ATX",
        "корпус для ПК mATX",
    ],
    "cooler": [
        "кулер для процессора",
        "водяное охлаждение 240",
        "водяное охлаждение 360",
    ],
}


def get_api_key(override: str | None = None) -> str | None:
    if override and override.strip():
        return override.strip()
    key = os.getenv("REEFAPI_KEY")
    return key.strip() if key else None


async def reef_search(api_key: str, query: str, page: int = 1) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=60.0) as client:
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


def _extract_brand(name: str, specs: dict | None) -> str | None:
    known = [
        "AMD", "Intel", "NVIDIA", "ASUS", "MSI", "Gigabyte", "ASRock",
        "Sapphire", "Palit", "GIGABYTE", "Kingston", "Corsair", "G.Skill",
        "Samsung", "WD", "Western Digital", "Seagate", "Crucial",
        "Deepcool", "DeepCool", "ID-Cooling", "be quiet", "Thermalright",
        "Arctic", "NZXT", "Fractal", "Lian Li", "Cooler Master",
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

    brand = item.get("brand") or _extract_brand(name, specs if isinstance(specs, dict) else None)
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
        existing_price.price = float(price_val) if price_val is not None else None
        existing_price.old_price = float(old_price) if old_price is not None else None
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
    max_per_query: int = 12,
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

    for cat_name, queries in CATEGORY_QUERIES.items():
        category = categories.get(cat_name)
        if not category:
            continue

        for query in queries:
            try:
                results = await reef_search(key, query, page=1)
                updated_queries += 1
                for item in results[:max_per_query]:
                    if upsert_component_from_dns(db, category, store, item):
                        added += 1
            except Exception:
                errors += 1
                continue

    db.commit()
    return {
        "components_added": added,
        "queries_ok": updated_queries,
        "errors": errors,
    }
