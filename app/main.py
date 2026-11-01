from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from typing import Optional
import json

from app.database import engine, get_db, Base
from app import models, schemas

# Create tables (no initial data)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="PC Component Comparator",
    description="Приложение для сравнения комплектующих ПК",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    {"name": "Citilink", "url": "https://www.citilink.ru"},
    {"name": "Regard", "url": "https://www.regard.ru"},
]


@app.get("/")
def root():
    return {
        "message": "PC Component Comparator API",
        "status": "ready",
        "note": "База данных пуста. Используйте POST /update-database для подготовки и наполнения.",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/update-database", response_model=schemas.UpdateDatabaseResponse)
def update_database(db: Session = Depends(get_db)):
    """
    Кнопка обновления базы.
    Создаёт базовые категории и магазины.
    Загрузка реальных товаров будет добавлена после подключения API-ключей.
    """
    categories_ready = 0
    for cat in DEFAULT_CATEGORIES:
        existing = db.query(models.Category).filter(models.Category.name == cat["name"]).first()
        if not existing:
            db.add(models.Category(**cat))
            categories_ready += 1

    for store in DEFAULT_STORES:
        existing = db.query(models.Store).filter(models.Store.name == store["name"]).first()
        if not existing:
            db.add(models.Store(**store))

    db.commit()

    total_categories = db.query(models.Category).count()

    return schemas.UpdateDatabaseResponse(
        status="accepted",
        message="Категории и магазины подготовлены. Загрузка товаров требует API-ключ (ReefAPI и т.п.).",
        note="Начальное наполнение товарами отсутствует по требованию.",
        components_added=0,
        categories_ready=total_categories,
    )


@app.get("/categories", response_model=list[schemas.Category])
def list_categories(db: Session = Depends(get_db)):
    return db.query(models.Category).order_by(models.Category.id).all()


@app.get("/components", response_model=list[schemas.ComponentListItem])
def list_components(
    category: Optional[str] = Query(None, description="Слаг категории: cpu, gpu, motherboard..."),
    q: Optional[str] = Query(None, description="Поиск по названию/бренду"),
    skip: int = 0,
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(models.Component).options(joinedload(models.Component.category), joinedload(models.Component.prices))

    if category:
        query = query.join(models.Category).filter(models.Category.name == category)

    if q:
        search = f"%{q}%"
        query = query.filter(
            or_(
                models.Component.name.ilike(search),
                models.Component.brand.ilike(search),
                models.Component.model.ilike(search),
            )
        )

    components = query.offset(skip).limit(limit).all()

    result = []
    for c in components:
        prices = [p.price for p in c.prices if p.price is not None]
        min_price = min(prices) if prices else None
        in_stock = any(p.in_stock for p in c.prices)
        result.append(
            schemas.ComponentListItem(
                id=c.id,
                name=c.name,
                brand=c.brand,
                model=c.model,
                image_url=c.image_url,
                category_id=c.category_id,
                category_name=c.category.name if c.category else None,
                min_price=min_price,
                in_stock=in_stock,
            )
        )
    return result


@app.get("/components/{component_id}", response_model=schemas.Component)
def get_component(component_id: int, db: Session = Depends(get_db)):
    component = (
        db.query(models.Component)
        .options(joinedload(models.Component.category), joinedload(models.Component.prices).joinedload(models.Price.store))
        .filter(models.Component.id == component_id)
        .first()
    )
    if not component:
        raise HTTPException(status_code=404, detail="Компонент не найден")
    # Parse specs if stored as string
    if isinstance(component.specs, str):
        try:
            component.specs = json.loads(component.specs)
        except Exception:
            pass
    return component


@app.get("/compare")
def compare_components(
    ids: str = Query(..., description="Список id через запятую, например 1,2,3"),
    db: Session = Depends(get_db),
):
    """
    Сравнение компонентов. Все должны быть одной категории.
    Максимум 4 позиции.
    """
    try:
        id_list = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный формат ids")

    if len(id_list) < 2:
        raise HTTPException(status_code=400, detail="Нужно минимум 2 компонента")
    if len(id_list) > 4:
        raise HTTPException(status_code=400, detail="Максимум 4 компонента")

    components = (
        db.query(models.Component)
        .options(joinedload(models.Component.category), joinedload(models.Component.prices).joinedload(models.Price.store))
        .filter(models.Component.id.in_(id_list))
        .all()
    )

    if len(components) != len(id_list):
        raise HTTPException(status_code=404, detail="Один или несколько компонентов не найдены")

    category_ids = {c.category_id for c in components}
    if len(category_ids) > 1:
        raise HTTPException(status_code=400, detail="Нельзя сравнивать компоненты разных категорий")

    for c in components:
        if isinstance(c.specs, str):
            try:
                c.specs = json.loads(c.specs)
            except Exception:
                pass

    return {
        "category": components[0].category.name if components[0].category else None,
        "category_ru": components[0].category.name_ru if components[0].category else None,
        "components": components,
    }
