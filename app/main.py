from fastapi import FastAPI, Depends, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from typing import Optional
import json
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv()

from app.database import engine, get_db, Base
from app import models, schemas
from app.services.dns_loader import load_dns_catalog, get_api_key

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="PC Component Comparator",
    description="Сравнение комплектующих ПК с данными DNS",
    version="0.3.0",
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

# Приоритетные ключи фильтров/сравнения по категориям (как в DNS)
CATEGORY_SPEC_PRIORITY: dict[str, list[str]] = {
    "cpu": [
        "Сокет",
        "Общее количество ядер",
        "Количество потоков",
        "Производительные ядра",
        "Базовая частота",
        "Максимальная частота",
        "Кэш L3",
        "Тепловыделение",
        "Графика",
        "Поддержка памяти",
    ],
    "gpu": [
        "Графический процессор",
        "Графический чип",
        "Объем видеопамяти",
        "Тип видеопамяти",
        "Разрядность шины памяти",
        "Частота видеочипа",
        "Частота памяти",
        "Интерфейс",
        "Рекомендуемая мощность БП",
        "Разъемы",
        "Длина видеокарты",
        "Толщина",
        "Количество вентиляторов",
    ],
    "motherboard": [
        "Сокет",
        "Чипсет",
        "Форм-фактор",
        "Тип поддерживаемой памяти",
        "Количество слотов памяти",
        "Максимальный объем памяти",
        "Разъемы M.2",
        "Слоты расширения",
        "Сетевой адаптер",
        "Wi-Fi",
    ],
    "ram": [
        "Тип памяти",
        "Объем одного модуля",
        "Суммарный объем",
        "Тактовая частота",
        "Тайминги",
        "Напряжение питания",
        "Радиатор",
        "Количество модулей",
    ],
    "ssd": [
        "Объем",
        "Форм-фактор",
        "Интерфейс",
        "Тип",
        "Скорость чтения",
        "Скорость записи",
        "Ресурс TBW",
        "NVMe",
    ],
    "hdd": [
        "Объем",
        "Скорость вращения",
        "Форм-фактор",
        "Интерфейс",
        "Кэш-память",
    ],
    "psu": [
        "Мощность",
        "Сертификат 80 PLUS",
        "Модульность",
        "Основной разъем питания",
        "Разъемы PCI-E",
        "Разъемы SATA",
        "Тип PFC",
    ],
    "case": [
        "Форм-фактор",
        "Поддерживаемые форм-факторы плат",
        "Отсеки 2.5",
        "Отсеки 3.5",
        "Максимальная длина видеокарты",
        "Максимальная высота кулера",
        "Блок питания",
    ],
    "cooler": [
        "Тип",
        "Сокет",
        "Совместимость с сокетами",
        "TDP",
        "Рассеиваемая мощность",
        "Количество вентиляторов",
        "Размер радиатора",
        "Подсветка",
    ],
}

# Ключи, которые не показываем в фильтрах «чужих» категорий (шум)
CATEGORY_SPEC_BLOCK: dict[str, set[str]] = {
    "gpu": {"Чипсет", "Сокет", "Общее количество ядер", "Производительные ядра"},
    "cpu": {"Чипсет", "Объем видеопамяти", "Тип видеопамяти", "Графический процессор"},
    "ram": {"Сокет", "Чипсет", "Объем видеопамяти"},
    "ssd": {"Сокет", "Чипсет", "Общее количество ядер"},
    "hdd": {"Сокет", "Чипсет", "Объем видеопамяти"},
    "psu": {"Сокет", "Чипсет", "Объем видеопамяти"},
    "case": {"Сокет", "Чипсет", "Объем видеопамяти"},
}


def _parse_specs(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _priority_keys_for(category: str | None) -> list[str]:
    if category and category in CATEGORY_SPEC_PRIORITY:
        return CATEGORY_SPEC_PRIORITY[category]
    # без категории — объединение топа
    keys: list[str] = []
    seen = set()
    for lst in CATEGORY_SPEC_PRIORITY.values():
        for k in lst:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    return keys


def _blocked_keys(category: str | None) -> set[str]:
    if category and category in CATEGORY_SPEC_BLOCK:
        return CATEGORY_SPEC_BLOCK[category]
    return set()


def _match_priority_key(actual_key: str, priority: list[str]) -> int | None:
    """Индекс приоритета, если actual_key совпадает или содержит приоритетный ключ."""
    ak = actual_key.lower()
    for i, p in enumerate(priority):
        pl = p.lower()
        if ak == pl or pl in ak or ak in pl:
            return i
    return None


def _component_to_list_item(c: models.Component) -> schemas.ComponentListItem:
    prices = [p for p in c.prices if p.price is not None]
    min_p = min((p.price for p in prices), default=None)
    old_p = None
    product_url = None
    if prices:
        best = min(prices, key=lambda p: p.price if p.price is not None else 1e18)
        old_p = best.old_price
        product_url = best.product_url
    return schemas.ComponentListItem(
        id=c.id,
        name=c.name,
        brand=c.brand,
        model=c.model,
        image_url=c.image_url,
        category_id=c.category_id,
        category_name=c.category.name if c.category else None,
        description=c.description,
        min_price=min_p,
        old_price=old_p,
        product_url=product_url,
        specs=_parse_specs(c.specs),
    )


@app.get("/")
def root():
    return {
        "message": "PC Component Comparator API",
        "status": "ready",
        "version": "0.3.0",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/update-database", response_model=schemas.UpdateDatabaseResponse)
async def update_database(
    body: Optional[schemas.UpdateDatabaseRequest] = Body(None),
    db: Session = Depends(get_db),
):
    for cat in DEFAULT_CATEGORIES:
        if not db.query(models.Category).filter(models.Category.name == cat["name"]).first():
            db.add(models.Category(**cat))
    for store in DEFAULT_STORES:
        if not db.query(models.Store).filter(models.Store.name == store["name"]).first():
            db.add(models.Store(**store))
    db.commit()
    total_categories = db.query(models.Category).count()

    api_key = body.api_key if body else None
    if not get_api_key(api_key):
        return schemas.UpdateDatabaseResponse(
            status="partial",
            message="Категории готовы. API-ключ не указан — товары не загружены.",
            note="Введите ключ ReefAPI на сайте и нажмите «Применить».",
            components_added=0,
            categories_ready=total_categories,
        )

    try:
        stats = await load_dns_catalog(
            db, max_per_query=24, pages_per_query=2, api_key=api_key
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка загрузки DNS: {e}")

    return schemas.UpdateDatabaseResponse(
        status="ok",
        message=f"Загружено из DNS: добавлено {stats['components_added']}, уникальных {stats.get('unique_seen', 0)}.",
        note=f"Запросов успешно: {stats['queries_ok']}, ошибок: {stats['errors']}",
        components_added=stats["components_added"],
        categories_ready=total_categories,
    )


@app.get("/categories", response_model=list[schemas.Category])
def list_categories(db: Session = Depends(get_db)):
    return db.query(models.Category).order_by(models.Category.id).all()


@app.get("/components", response_model=schemas.ComponentsPage)
def list_components(
    category: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    sort: str = Query("price_asc"),
    brand: Optional[str] = Query(None),
    price_min: Optional[float] = Query(None),
    price_max: Optional[float] = Query(None),
    spec: Optional[list[str]] = Query(None),
    skip: int = 0,
    limit: int = Query(48, le=120),
    db: Session = Depends(get_db),
):
    query = db.query(models.Component).options(
        joinedload(models.Component.category),
        joinedload(models.Component.prices),
    )

    if category:
        query = query.join(models.Category).filter(models.Category.name == category)

    if q:
        search = f"%{q}%"
        query = query.filter(
            or_(
                models.Component.name.ilike(search),
                models.Component.brand.ilike(search),
                models.Component.model.ilike(search),
                models.Component.description.ilike(search),
            )
        )

    if brand:
        brands = [b.strip() for b in brand.split(",") if b.strip()]
        if brands:
            query = query.filter(or_(*[models.Component.brand.ilike(b) for b in brands]))

    components = query.all()

    filtered: list[models.Component] = []
    spec_filters: list[tuple[str, str]] = []
    if spec:
        for s in spec:
            if ":" in s:
                k, v = s.split(":", 1)
                spec_filters.append((k.strip(), v.strip()))

    for c in components:
        prices = [p.price for p in c.prices if p.price is not None]
        min_p = min(prices) if prices else None

        if price_min is not None and (min_p is None or min_p < price_min):
            continue
        if price_max is not None and (min_p is None or min_p > price_max):
            continue

        specs = _parse_specs(c.specs)
        ok = True
        for sk, sv in spec_filters:
            # гибкое совпадение ключа
            matched_val = ""
            for actual_k, actual_v in specs.items():
                if actual_k == sk or sk.lower() in actual_k.lower() or actual_k.lower() in sk.lower():
                    matched_val = str(actual_v)
                    break
            if sv.lower() not in matched_val.lower():
                ok = False
                break
        if not ok:
            continue

        filtered.append(c)

    def sort_key(c: models.Component):
        prices = [p.price for p in c.prices if p.price is not None]
        min_p = min(prices) if prices else None
        name = (c.name or "").lower()
        if sort == "price_desc":
            return (min_p is None, -(min_p or 0), name)
        if sort == "name_asc":
            return (name,)
        if sort == "name_desc":
            return (name,)
        return (min_p is None, min_p or 0, name)

    if sort == "name_desc":
        filtered.sort(key=lambda c: (c.name or "").lower(), reverse=True)
    else:
        filtered.sort(key=sort_key)

    total = len(filtered)
    page = filtered[skip : skip + limit]
    items = [_component_to_list_item(c) for c in page]
    return schemas.ComponentsPage(items=items, total=total, skip=skip, limit=limit)


@app.get("/facets", response_model=schemas.FacetsResponse)
def get_facets(
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(models.Component).options(joinedload(models.Component.prices))
    if category:
        query = query.join(models.Category).filter(models.Category.name == category)
    components = query.all()

    brand_counts: dict[str, int] = defaultdict(int)
    spec_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    key_freq: dict[str, int] = defaultdict(int)
    prices: list[float] = []

    blocked = _blocked_keys(category)
    priority = _priority_keys_for(category)

    for c in components:
        if c.brand:
            brand_counts[c.brand] += 1
        for p in c.prices:
            if p.price is not None:
                prices.append(p.price)
        specs = _parse_specs(c.specs)
        for key, val in specs.items():
            if not val or key in blocked:
                continue
            key_freq[key] += 1
            spec_counts[key][str(val)] += 1

    # Выбираем ключи: сначала приоритетные, которые реально есть, потом частые
    chosen_keys: list[str] = []
    used = set()

    for pkey in priority:
        # найти реальный ключ в данных
        match = None
        for actual in key_freq:
            if actual in used or actual in blocked:
                continue
            idx = _match_priority_key(actual, [pkey])
            if idx is not None:
                match = actual
                break
        if match:
            chosen_keys.append(match)
            used.add(match)

    # добить часто встречающимися (не в blocklist)
    for key, _cnt in sorted(key_freq.items(), key=lambda x: -x[1]):
        if key in used or key in blocked:
            continue
        if len(chosen_keys) >= 8:
            break
        # не больше 25 уникальных значений — иначе бесполезный фильтр
        if len(spec_counts[key]) > 40:
            continue
        chosen_keys.append(key)
        used.add(key)

    brands = [
        schemas.FacetValue(value=k, count=v)
        for k, v in sorted(brand_counts.items(), key=lambda x: (-x[1], x[0]))
    ]

    facets = []
    for key in chosen_keys:
        vals = spec_counts.get(key) or {}
        if not vals:
            continue
        facets.append(
            schemas.Facet(
                key=key,
                values=[
                    schemas.FacetValue(value=k, count=v)
                    for k, v in sorted(vals.items(), key=lambda x: (-x[1], x[0]))[:25]
                ],
            )
        )

    return schemas.FacetsResponse(
        brands=brands[:40],
        specs=facets,
        price_min=min(prices) if prices else None,
        price_max=max(prices) if prices else None,
    )


@app.get("/components/{component_id}", response_model=schemas.Component)
def get_component(component_id: int, db: Session = Depends(get_db)):
    component = (
        db.query(models.Component)
        .options(
            joinedload(models.Component.category),
            joinedload(models.Component.prices).joinedload(models.Price.store),
        )
        .filter(models.Component.id == component_id)
        .first()
    )
    if not component:
        raise HTTPException(status_code=404, detail="Компонент не найден")
    component.specs = _parse_specs(component.specs)
    return component


@app.get("/compare")
def compare_components(
    ids: str = Query(..., description="id через запятую"),
    db: Session = Depends(get_db),
):
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
        .options(
            joinedload(models.Component.category),
            joinedload(models.Component.prices).joinedload(models.Price.store),
        )
        .filter(models.Component.id.in_(id_list))
        .all()
    )

    if len(components) != len(id_list):
        raise HTTPException(status_code=404, detail="Один или несколько компонентов не найдены")

    by_id = {c.id: c for c in components}
    ordered = [by_id[i] for i in id_list if i in by_id]

    category_ids = {c.category_id for c in ordered}
    if len(category_ids) > 1:
        raise HTTPException(status_code=400, detail="Нельзя сравнивать компоненты разных категорий")

    for c in ordered:
        c.specs = _parse_specs(c.specs)

    cat_name = ordered[0].category.name if ordered[0].category else None
    priority = _priority_keys_for(cat_name)
    blocked = _blocked_keys(cat_name)

    all_keys: list[str] = []
    seen = set()
    for c in ordered:
        for k in (c.specs or {}):
            if k in blocked or k in seen:
                continue
            seen.add(k)
            all_keys.append(k)

    # сортировка ключей: приоритетные сверху, остальные по алфавиту
    def key_rank(k: str):
        m = _match_priority_key(k, priority)
        if m is not None:
            return (0, m, k.lower())
        return (1, 999, k.lower())

    all_keys.sort(key=key_rank)

    return {
        "category": cat_name,
        "category_ru": ordered[0].category.name_ru if ordered[0].category else None,
        "spec_keys": all_keys,
        "components": ordered,
    }
