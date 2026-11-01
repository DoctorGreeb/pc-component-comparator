from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import engine, get_db, Base
from app import models

# Create tables (no initial data)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="PC Component Comparator",
    description="Приложение для сравнения комплектующих ПК",
    version="0.1.0",
)


@app.get("/")
def root():
    return {
        "message": "PC Component Comparator API",
        "status": "ready",
        "note": "База данных пуста. Используйте /update-базу для наполнения.",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/update-database")
def update_database(db: Session = Depends(get_db)):
    """
    Кнопка обновления базы.
    На данном этапе — заглушка.
    В будущем здесь будет логика загрузки данных из DNS (ReefAPI и т.п.)
    и открытых источников характеристик.
    """
    # TODO: реализовать загрузку
    # 1. Проверить/создать категории и магазины
    # 2. Запросить данные через API
    # 3. Нормализовать и сохранить в БД

    return {
        "status": "accepted",
        "message": "Обновление базы запущено (заглушка). Реализация загрузки данных будет добавлена в следующих итерациях.",
        "note": "Для работы требуется API-ключ (например ReefAPI для DNS).",
    }


@app.get("/components")
def list_components(
    category: str | None = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    query = db.query(models.Component)
    if category:
        query = query.join(models.Category).filter(models.Category.name == category)
    components = query.offset(skip).limit(limit).all()
    return components


@app.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    return db.query(models.Category).all()
