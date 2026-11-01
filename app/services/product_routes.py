"""Роуты карточки товара: обогащение описания/отзывов и поиск характеристик."""
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.services.product_enrichment import enrich_product_page
from app.services.dns_loader import get_api_key, reef_search
from app.services.product_enrichment import search_specs_on_web

router = APIRouter()


def _normalized_name(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"[^a-zа-яё0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _is_same_product(expected: str, candidate: str) -> bool:
    left, right = _normalized_name(expected), _normalized_name(candidate)
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    left_tokens, right_tokens = set(left.split()), set(right.split())
    # Не принимаем похожие товары, если совпадает лишь бренд или серия.
    if len(left_tokens) < 3 or len(right_tokens) < 3:
        return False
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))
    return overlap >= 0.88


@router.get("/components/{component_id}/enrich")
async def enrich_component_page(component_id: int, db: Session = Depends(get_db)):
    """Описание (Wikipedia/DDG), ссылка производителя, сниппеты отзывов — без API-ключа."""
    component = db.query(models.Component).filter(models.Component.id == component_id).first()
    if not component:
        raise HTTPException(status_code=404, detail="Компонент не найден")
    data = await enrich_product_page(
        name=component.name,
        brand=component.brand,
        model=component.model,
        existing_description=component.description,
    )
    if data.get("description") and not (component.description or "").strip():
        try:
            component.description = data["description"][:4000]
            db.commit()
        except Exception:
            db.rollback()
    return data


@router.post("/components/{component_id}/find-specs")
async def find_component_specs(
    component_id: int,
    body: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    """Сначала ищет в DNS через ReefAPI, затем автоматически — в открытом интернете."""
    component = db.query(models.Component).filter(models.Component.id == component_id).first()
    if not component:
        raise HTTPException(status_code=404, detail="Компонент не найден")

    existing = component.specs
    if isinstance(existing, str):
        try:
            existing = json.loads(existing)
        except (TypeError, ValueError):
            existing = {}
    if isinstance(existing, dict) and any(str(v).strip() for v in existing.values() if v is not None):
        return {"status": "already_filled", "message": "Характеристики уже заполнены.", "specs": existing}

    api_key = get_api_key((body or {}).get("api_key"))
    api_error = None
    if api_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=8.0)) as client:
                results = await reef_search(client, api_key, component.name[:180], page=1)
            best = next(
                (
                    product for product in results
                    if _is_same_product(component.name, str(product.get("name") or ""))
                    and isinstance(product.get("specs"), dict)
                    and any(str(v).strip() for v in product["specs"].values() if v is not None)
                ),
                None,
            )
            if best:
                component.specs = json.dumps(best["specs"], ensure_ascii=False)
                db.commit()
                return {
                    "status": "ok",
                    "message": f"Найдено характеристик: {len(best['specs'])}. Источник: DNS через ReefAPI. Данные сохранены.",
                    "specs": best["specs"],
                    "source": "DNS / ReefAPI",
                    "source_url": best.get("url"),
                }
        except Exception as exc:
            api_error = f"{type(exc).__name__}: {str(exc)[:180]}"

    # No key, no DNS match, exhausted credits, or ReefAPI error — try public web.
    try:
        web_result = await search_specs_on_web(
            name=component.name,
            brand=component.brand,
            model=component.model,
        )
    except Exception as exc:
        web_result = None
        web_error = f"{type(exc).__name__}: {str(exc)[:160]}"
    else:
        web_error = None

    if web_result and isinstance(web_result.get("specs"), dict):
        specs = web_result["specs"]
        component.specs = json.dumps(specs, ensure_ascii=False)
        db.commit()
        return {
            "status": "ok",
            "message": f"Найдено характеристик: {len(specs)}. Источник: открытый интернет. Данные сохранены.",
            "specs": specs,
            "source": web_result.get("source") or "web",
            "source_title": web_result.get("source_title"),
            "source_url": web_result.get("source_url"),
        }

    details = []
    if not api_key:
        details.append("ключ ReefAPI не передан из браузера")
    elif api_error:
        details.append(f"ReefAPI: {api_error}")
    if web_error:
        details.append(f"веб-поиск: {web_error}")
    suffix = " Причина: " + "; ".join(details) if details else ""
    return {
        "status": "not_found",
        "message": "Не удалось найти подтверждённые характеристики этой модели ни в DNS, ни в открытой веб-выдаче." + suffix,
        "specs": {},
    }
