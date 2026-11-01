"""Роуты карточки товара: обогащение и автоматический поиск характеристик."""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.services.product_enrichment import enrich_product_page, search_specs_on_web

router = APIRouter()


@router.get("/components/{component_id}/enrich")
async def enrich_component_page(component_id: int, db: Session = Depends(get_db)):
    component = db.query(models.Component).filter(models.Component.id == component_id).first()
    if not component:
        raise HTTPException(status_code=404, detail="Компонент не найден")
    data = await enrich_product_page(component.name, component.brand, component.model, component.description)
    if data.get("description") and not (component.description or "").strip():
        try:
            component.description = data["description"][:4000]
            db.commit()
        except Exception:
            db.rollback()
    return data


@router.post("/components/{component_id}/find-specs")
async def find_component_specs(component_id: int, db: Session = Depends(get_db)):
    """Поиск без ReefAPI: сначала сниппеты, затем страницы магазинов и производителей."""
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

    result = await search_specs_on_web(component.name, component.brand, component.model)
    if result and isinstance(result.get("specs"), dict) and result["specs"]:
        specs = result["specs"]
        component.specs = json.dumps(specs, ensure_ascii=False)
        db.commit()
        return {
            "status": "ok",
            "message": f"Автоматически найдено характеристик: {len(specs)}. Данные сохранены.",
            "specs": specs,
            "source": result.get("source"),
            "source_title": result.get("source_title"),
            "source_url": result.get("source_url"),
        }
    return {
        "status": "not_found",
        "message": "Поиск завершён, но сайты не отдали читаемую таблицу характеристик. Можно повторить поиск позже.",
        "specs": {},
    }
