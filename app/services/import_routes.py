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
    @app.post("/catalog/import-stream")
    async def import_catalog_stream(
        body: schemas.CatalogImportRequest = Body(...),
        db: Session = Depends(get_db),
    ):
        async def generate():
            try:
                yield _sse({"pct": 2, "op": "Подготовка категорий и магазинов…"})
                for cat in DEFAULT_CATEGORIES:
                    if not db.query(models.Category).filter(models.Category.name == cat["name"]).first():
                        db.add(models.Category(**cat))
                for store in DEFAULT_STORES:
                    if not db.query(models.Store).filter(models.Store.name == store["name"]).first():
                        db.add(models.Store(**store))
                db.commit()
                cats = {c.name: c for c in db.query(models.Category).all()}
                stores = {s.name: s for s in db.query(models.Store).all()}

                items = body.items or []
                total = len(items)
                if total == 0:
                    yield _sse({
                        "pct": 100,
                        "op": "Пустой список items",
                        "result": {"status": "error", "message": "Нет items", "added": 0, "updated": 0},
                    })
                    return

                added = updated = skipped = 0
                yield _sse({"pct": 5, "op": f"Импорт JSON: {total} позиций…"})

                for i, item in enumerate(items, 1):
                    pct = 5 + int(90 * i / total)
                    short = (item.name or "?")[:64]
                    cat = cats.get(item.category)
                    if not cat:
                        skipped += 1
                        yield _sse({
                            "pct": pct,
                            "op": f"[{i}/{total}] Пропуск (нет категории «{item.category}»): {short}",
                        })
                        continue
                    store = stores.get(item.store) or stores.get("DNS")
                    if not store:
                        skipped += 1
                        yield _sse({
                            "pct": pct,
                            "op": f"[{i}/{total}] Пропуск (нет магазина): {short}",
                        })
                        continue

                    external_id = item.external_id or f"import-{item.category}-{item.name}"[:120]
                    existing_price = (
                        db.query(models.Price)
                        .filter(
                            models.Price.store_id == store.id,
                            models.Price.external_id == str(external_id),
                        )
                        .first()
                    )
                    specs_json = json.dumps(item.specs, ensure_ascii=False) if item.specs else None
                    action = "обновляю" if existing_price else "добавляю"
                    price_txt = f"{item.price} ₽" if item.price is not None else "без цены"
                    if item.image_url:
                        try:
                            img_note = f", фото ← {urlparse(item.image_url).netloc or 'url'}"
                        except Exception:
                            img_note = ", с фото"
                    else:
                        img_note = ", без фото"

                    yield _sse({
                        "pct": pct,
                        "op": f"[{i}/{total}] {action}: {short} ({item.category}, {price_txt}{img_note})",
                    })

                    if existing_price:
                        comp = existing_price.component
                        comp.name = item.name
                        if item.brand:
                            comp.brand = item.brand
                        if item.image_url:
                            comp.image_url = item.image_url
                        if item.description:
                            comp.description = item.description
                        if specs_json:
                            comp.specs = specs_json
                        if item.price is not None:
                            existing_price.price = float(item.price)
                        existing_price.old_price = item.old_price
                        existing_price.product_url = item.product_url or existing_price.product_url
                        updated += 1
                    else:
                        comp = models.Component(
                            category_id=cat.id,
                            name=item.name,
                            brand=item.brand,
                            description=item.description,
                            image_url=item.image_url,
                            specs=specs_json,
                        )
                        db.add(comp)
                        db.flush()
                        db.add(
                            models.Price(
                                component_id=comp.id,
                                store_id=store.id,
                                price=float(item.price) if item.price is not None else None,
                                old_price=item.old_price,
                                in_stock=True,
                                product_url=item.product_url,
                                external_id=str(external_id),
                            )
                        )
                        added += 1

                    if i % 25 == 0:
                        db.commit()

                db.commit()
                msg = (
                    f"Импорт завершён: +{added}, обновлено {updated}"
                    + (f", пропущено {skipped}" if skipped else "")
                )
                yield _sse({
                    "pct": 100,
                    "op": "Готово",
                    "result": {
                        "status": "ok",
                        "message": msg,
                        "added": added,
                        "updated": updated,
                        "components_added": added,
                    },
                })
            except Exception as e:
                db.rollback()
                yield _sse({
                    "pct": 100,
                    "op": "Ошибка импорта",
                    "error": str(e),
                    "result": {"status": "error", "message": str(e), "added": 0, "updated": 0},
                })

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
