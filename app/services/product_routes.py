"""Роуты карточки товара: обогащение описания/отзывов."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.services.product_enrichment import enrich_product_page

router = APIRouter()


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
