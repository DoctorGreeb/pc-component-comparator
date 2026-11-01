"""
Подгрузка цен с Яндекс Маркета и Wildberries через ReefAPI
(не DNS, не обход антибота — только официальный data-gateway).
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable, Awaitable

import httpx
from sqlalchemy.orm import Session

from app import models
from app.services.dns_loader import (
    CATEGORY_QUERIES,
    ECONOMY_QUERIES,
    CreditsExhaustedError,
    get_api_key,
    _extract_brand,
)

REEF_API_BASE = "https://api.reefapi.com"
ProgressCallback = Callable[[str], Awaitable[None]]

async def _progress(callback: ProgressCallback | None, message: str) -> None:
    if callback:
        await callback(message)

# Короткие запросы по категориям (экономия кредитов)
YM_QUERIES: dict[str, list[str]] = {
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

WB_QUERIES = YM_QUERIES  # те же формулировки


def _norm_name(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^\wа-яё]+", " ", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()


async def _reef_post(
    client: httpx.AsyncClient,
    api_key: str,
    path: str,
    body: dict,
) -> dict[str, Any]:
    resp = await client.post(
        f"{REEF_API_BASE}{path}",
        headers={"x-api-key": api_key, "content-type": "application/json"},
        json=body,
    )
    if resp.status_code in (401, 403):
        raise CreditsExhaustedError("API-ключ отклонён")
    if resp.status_code == 402:
        raise CreditsExhaustedError("Кредиты ReefAPI закончились")
    remaining = resp.headers.get("X-Credits-Remaining")
    if remaining is not None:
        try:
            if float(remaining) <= 0:
                raise CreditsExhaustedError("Кредиты ReefAPI закончились")
        except ValueError:
            pass
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        err = str((data.get("error") or {}).get("message") or "").lower()
        if "credit" in err or "balance" in err or "quota" in err:
            raise CreditsExhaustedError("Кредиты ReefAPI закончились")
        return {}
    return data.get("data") or {}


def _ensure_store(db: Session, name: str, url: str) -> models.Store:
    store = db.query(models.Store).filter(models.Store.name == name).first()
    if not store:
        store = models.Store(name=name, url=url)
        db.add(store)
        db.flush()
    return store


def _find_or_create_component(
    db: Session,
    category: models.Category,
    name: str,
    brand: str | None,
    image: str | None,
    description: str | None = None,
) -> models.Component:
    # точное совпадение имени
    existing = (
        db.query(models.Component)
        .filter(
            models.Component.category_id == category.id,
            models.Component.name == name,
        )
        .first()
    )
    if existing:
        if image and not existing.image_url:
            existing.image_url = image
        if brand and not existing.brand:
            existing.brand = brand
        return existing

    # мягкое совпадение по нормализованному имени (первые 60 символов)
    needle = _norm_name(name)[:60]
    if needle:
        candidates = (
            db.query(models.Component)
            .filter(models.Component.category_id == category.id)
            .limit(500)
            .all()
        )
        for c in candidates:
            if _norm_name(c.name)[:60] == needle:
                return c

    comp = models.Component(
        category_id=category.id,
        name=name,
        brand=brand or _extract_brand(name),
        description=description,
        image_url=image,
        specs=None,
    )
    db.add(comp)
    db.flush()
    return comp


def _upsert_price(
    db: Session,
    component: models.Component,
    store: models.Store,
    *,
    price: float | None,
    old_price: float | None,
    url: str | None,
    external_id: str,
    in_stock: bool,
) -> bool:
    """True если создана новая цена (новый товар-магазин)."""
    existing = (
        db.query(models.Price)
        .filter(
            models.Price.store_id == store.id,
            models.Price.external_id == str(external_id),
        )
        .first()
    )
    if existing:
        if price is not None:
            existing.price = float(price)
        if old_price is not None:
            existing.old_price = float(old_price)
        existing.product_url = url or existing.product_url
        existing.in_stock = in_stock
        return False

    db.add(
        models.Price(
            component_id=component.id,
            store_id=store.id,
            price=float(price) if price is not None else None,
            old_price=float(old_price) if old_price is not None else None,
            in_stock=in_stock,
            product_url=url,
            external_id=str(external_id),
        )
    )
    return True


async def load_yandex_market(
    db: Session,
    api_key: str,
    economy: bool = True,
    max_per_query: int = 12,
    on_progress: ProgressCallback | None = None,
) -> dict[str, int]:
    categories = {c.name: c for c in db.query(models.Category).all()}
    store = _ensure_store(db, "Яндекс Маркет", "https://market.yandex.ru")
    queries_map = YM_QUERIES if economy else {
        k: (CATEGORY_QUERIES.get(k) or YM_QUERIES.get(k) or [])[:4]
        for k in YM_QUERIES
    }

    added = 0
    queries_ok = 0
    errors = 0

    all_queries = [(cat, query) for cat, queries in queries_map.items() for query in queries if categories.get(cat)]
    query_index = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=12.0)) as client:
        for cat_name, queries in queries_map.items():
            cat = categories.get(cat_name)
            if not cat:
                continue
            for query in queries:
                query_index += 1
                endpoint = REEF_API_BASE + "/yandex-market/v1/search"
                await _progress(on_progress, f"Яндекс Маркет · запрос {query_index}/{len(all_queries)} · POST {endpoint} · query=\"{query}\"")
                started = asyncio.get_running_loop().time()
                try:
                    data = await _reef_post(
                        client,
                        api_key,
                        "/yandex-market/v1/search",
                        {"query": query, "page": 1},
                    )
                    results = data.get("results") or []
                    queries_ok += 1
                    await _progress(on_progress, f"Яндекс Маркет · ответ {query_index}/{len(all_queries)} · HTTP 200 · получено {len(results)} позиций · {asyncio.get_running_loop().time()-started:.1f} с")
                    for item in results[:max_per_query]:
                        name = item.get("title") or ""
                        if not name:
                            continue
                        pid = str(item.get("product_id") or item.get("sku_id") or "")
                        if not pid:
                            continue
                        price = item.get("price")
                        old = item.get("was_price")
                        comp = _find_or_create_component(
                            db,
                            cat,
                            name,
                            _extract_brand(name),
                            item.get("image"),
                        )
                        if _upsert_price(
                            db,
                            comp,
                            store,
                            price=float(price) if price is not None else None,
                            old_price=float(old) if old is not None else None,
                            url=item.get("url"),
                            external_id=f"ym-{pid}",
                            in_stock=bool(item.get("available")),
                        ):
                            added += 1
                    db.commit()
                except CreditsExhaustedError:
                    raise
                except Exception as exc:
                    errors += 1
                    await _progress(on_progress, f"Яндекс Маркет · ОШИБКА запроса {query_index}/{len(all_queries)} · {type(exc).__name__}: {exc}")
                    continue

    return {"components_added": added, "queries_ok": queries_ok, "errors": errors}


async def load_wildberries(
    db: Session,
    api_key: str,
    economy: bool = True,
    max_per_query: int = 15,
    on_progress: ProgressCallback | None = None,
) -> dict[str, int]:
    categories = {c.name: c for c in db.query(models.Category).all()}
    store = _ensure_store(db, "Wildberries", "https://www.wildberries.ru")
    queries_map = WB_QUERIES if economy else {
        k: (CATEGORY_QUERIES.get(k) or WB_QUERIES.get(k) or [])[:4]
        for k in WB_QUERIES
    }

    added = 0
    queries_ok = 0
    errors = 0

    all_queries = [(cat, query) for cat, queries in queries_map.items() for query in queries if categories.get(cat)]
    query_index = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=12.0)) as client:
        for cat_name, queries in queries_map.items():
            cat = categories.get(cat_name)
            if not cat:
                continue
            for query in queries:
                query_index += 1
                endpoint = REEF_API_BASE + "/wildberries/v1/search"
                await _progress(on_progress, f"Wildberries · запрос {query_index}/{len(all_queries)} · POST {endpoint} · query=\"{query}\" · country=ru")
                started = asyncio.get_running_loop().time()
                try:
                    data = await _reef_post(
                        client,
                        api_key,
                        "/wildberries/v1/search",
                        {"query": query, "page": 1, "country": "ru"},
                    )
                    results = data.get("results") or []
                    queries_ok += 1
                    await _progress(on_progress, f"Wildberries · ответ {query_index}/{len(all_queries)} · HTTP 200 · получено {len(results)} позиций · {asyncio.get_running_loop().time()-started:.1f} с")
                    for item in results[:max_per_query]:
                        name = item.get("title") or ""
                        if not name:
                            continue
                        pid = str(item.get("product_id") or "")
                        if not pid:
                            continue
                        brand = item.get("brand") or _extract_brand(name)
                        price = item.get("price")
                        old = item.get("was_price")
                        comp = _find_or_create_component(
                            db,
                            cat,
                            name,
                            brand,
                            item.get("image"),
                        )
                        if _upsert_price(
                            db,
                            comp,
                            store,
                            price=float(price) if price is not None else None,
                            old_price=float(old) if old is not None else None,
                            url=item.get("url"),
                            external_id=f"wb-{pid}",
                            in_stock=bool(item.get("available")),
                        ):
                            added += 1
                    db.commit()
                except CreditsExhaustedError:
                    raise
                except Exception as exc:
                    errors += 1
                    await _progress(on_progress, f"Wildberries · ОШИБКА запроса {query_index}/{len(all_queries)} · {type(exc).__name__}: {exc}")
                    continue

    return {"components_added": added, "queries_ok": queries_ok, "errors": errors}


async def load_extra_stores(
    db: Session,
    api_key: str | None = None,
    economy: bool = True,
    sources: list[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    key = get_api_key(api_key)
    if not key:
        raise RuntimeError("REEFAPI_KEY не задан")

    sources = sources or ["yandex_market", "wildberries"]
    out: dict[str, Any] = {"sources": {}}

    if "yandex_market" in sources:
        try:
            await _progress(on_progress, "Яндекс Маркет · начало синхронизации")
            out["sources"]["yandex_market"] = await load_yandex_market(
                db, key, economy=economy, on_progress=on_progress
            )
            await _progress(on_progress, "Яндекс Маркет · завершено · " + str(out["sources"]["yandex_market"].get("components_added", 0)) + " новых позиций; ошибок: " + str(out["sources"]["yandex_market"].get("errors", 0)))
        except CreditsExhaustedError:
            raise
        except Exception as e:
            out["sources"]["yandex_market"] = {"error": str(e)}

    if "wildberries" in sources:
        try:
            await _progress(on_progress, "Wildberries · начало синхронизации")
            out["sources"]["wildberries"] = await load_wildberries(
                db, key, economy=economy, on_progress=on_progress
            )
            await _progress(on_progress, "Wildberries · завершено · " + str(out["sources"]["wildberries"].get("components_added", 0)) + " новых позиций; ошибок: " + str(out["sources"]["wildberries"].get("errors", 0)))
        except CreditsExhaustedError:
            raise
        except Exception as e:
            out["sources"]["wildberries"] = {"error": str(e)}

    total_added = 0
    for s in out["sources"].values():
        if isinstance(s, dict):
            total_added += int(s.get("components_added") or 0)
    out["components_added"] = total_added
    return out
