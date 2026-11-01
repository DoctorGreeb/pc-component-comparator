"""SSE-импорт каталога с подробным прогрессом по каждой позиции."""
from __future__ import annotations

import json
from urllib.parse import urlparse

from fastapi import Body, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

DEFAULT_CATEGORIES = [
    {"name": "cpu", "name_ru": "Процессоры"},
    {"name": "gpu", "name_ru": "Видеокарты"},
    {"name": "motherboard", "name_ru": "Материнские платы"},
    {"name": "ram", "name_ru": "Оперативная память"},
    {"name": "ssd", "name_ru": "SSD накопители"},
    {"name": "hdd", "name_ru": "HDD накопители"},
    {"name": "psu", "name_ru": "Блоки питания"},
    {"name": "case", "name_ru": "Корпуса"},
    {"name": "cooler", "name_ru": "Системы охлаждения"},
]
DEFAULT_STORES = [
    {"name": "DNS", "url": "https://www.dns-shop.ru"},
    {"name": "Яндекс Маркет", "url": "https://market.yandex.ru"},
    {"name": "Wildberries", "url": "https://www.wildberries.ru"},
    {"name": "Citilink", "url": "https://www.citilink.ru"},
    {"name": "Regard", "url": "https://www.regard.ru"},
]


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def register(app):
    try:
        from app.services import product_routes
        app.include_router(product_routes.router)
    except Exception:
        pass

    @app.post("/catalog/import-stream")
    async def import_catalog_stream(
        body: schemas.CatalogImportRequest = Body(...),
        db: Session = Depends(get_db),
    ):
        async def generate():
            items = body.items or []
            total = len(items)
            if total == 0:
                yield _sse({"pct": 100, "op": "Пустой импорт", "result": {"status": "ok", "message": "Нет позиций", "components_added": 0, "added": 0, "updated": 0}})
                return

            for cat in DEFAULT_CATEGORIES:
                if not db.query(models.Category).filter(models.Category.name == cat["name"]).first():
                    db.add(models.Category(**cat))
            for store in DEFAULT_STORES:
                if not db.query(models.Store).filter(models.Store.name == store["name"]).first():
                    db.add(models.Store(**store))
            db.commit()

            cats = {c.name: c for c in db.query(models.Category).all()}
            stores = {s.name: s for s in db.query(models.Store).all()}
            added = updated = 0

            for idx, item in enumerate(items, start=1):
                try:
                    cat_name = (getattr(item, "category", None) or "cpu").strip().lower()
                    if cat_name not in cats:
                        cat_name = "cpu"
                    cat = cats[cat_name]
                    name = (getattr(item, "name", None) or "").strip()
                    if not name:
                        yield _sse({"pct": int(idx / total * 100), "op": f"[{idx}/{total}] пропуск: пустое имя"})
                        continue

                    brand = getattr(item, "brand", None)
                    store_name = getattr(item, "store", None) or "DNS"
                    store = stores.get(store_name) or list(stores.values())[0]

                    existing = (
                        db.query(models.Component)
                        .filter(models.Component.category_id == cat.id, models.Component.name == name)
                        .first()
                    )

                    specs = getattr(item, "specs", None)
                    specs_str = json.dumps(specs, ensure_ascii=False) if isinstance(specs, dict) else (specs if isinstance(specs, str) else None)
                    image_url = getattr(item, "image_url", None)
                    description = getattr(item, "description", None)
                    price = getattr(item, "price", None)
                    old_price = getattr(item, "old_price", None)
                    product_url = getattr(item, "product_url", None)
                    external_id = getattr(item, "external_id", None)

                    img_note = ""
                    if image_url:
                        try:
                            host = urlparse(image_url).netloc or "файл"
                            img_note = f", фото ← {host}"
                        except Exception:
                            img_note = ", с фото"

                    if existing:
                        if description and not existing.description:
                            existing.description = description
                        if image_url and (not existing.image_url or str(existing.image_url).startswith("data:")):
                            existing.image_url = image_url
                        if specs_str and not existing.specs:
                            existing.specs = specs_str
                        if brand and not existing.brand:
                            existing.brand = brand
                        if price is not None:
                            pr = next((p for p in existing.prices if p.store_id == store.id), None)
                            if pr:
                                pr.price = float(price)
                                if old_price is not None:
                                    pr.old_price = float(old_price)
                                if product_url:
                                    pr.product_url = product_url
                            else:
                                db.add(models.Price(component_id=existing.id, store_id=store.id, price=float(price),
                                    old_price=float(old_price) if old_price is not None else None,
                                    product_url=product_url, external_id=external_id, in_stock=True))
                        updated += 1
                        op = f"[{idx}/{total}] обновляю: {name} ({cat_name}" + (f", {int(price)} ₽" if price else "") + img_note + ")"
                    else:
                        comp = models.Component(
                            category_id=cat.id, name=name, brand=brand,
                            description=description, image_url=image_url, specs=specs_str,
                        )
                        db.add(comp)
                        db.flush()
                        if price is not None:
                            db.add(models.Price(component_id=comp.id, store_id=store.id, price=float(price),
                                old_price=float(old_price) if old_price is not None else None,
                                product_url=product_url, external_id=external_id, in_stock=True))
                        added += 1
                        op = f"[{idx}/{total}] добавляю: {name} ({cat_name}" + (f", {int(price)} ₽" if price else "") + img_note + ")"

                    if idx % 20 == 0:
                        db.commit()
                    yield _sse({"pct": int(idx / total * 100), "op": op})
                except Exception as e:
                    yield _sse({"pct": int(idx / total * 100), "op": f"[{idx}/{total}] ошибка: {e}"})

            db.commit()
            yield _sse({
                "pct": 100,
                "op": "Импорт завершён",
                "result": {
                    "status": "ok",
                    "message": f"Импорт: +{added}, обновлено {updated}",
                    "components_added": added,
                    "added": added,
                    "updated": updated,
                },
            })

        return StreamingResponse(generate(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
        })
