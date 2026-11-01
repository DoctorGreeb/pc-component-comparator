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
from app.services.dns_loader import load_dns_catalog, get_api_key, CreditsExhaustedError
from app.services.multi_store_loader import load_extra_stores
from app.services.free_loader import load_free_sources

Base.metadata.create_all(bind=engine)
app = FastAPI(title="PC Component Comparator", version="0.4.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

DEFAULT_CATEGORIES = [
    {"name": "cpu", "name_ru": "Процессоры"}, {"name": "gpu", "name_ru": "Видеокарты"},
    {"name": "motherboard", "name_ru": "Материнские платы"}, {"name": "ram", "name_ru": "Оперативная память"},
    {"name": "ssd", "name_ru": "SSD накопители"}, {"name": "hdd", "name_ru": "HDD накопители"},
    {"name": "psu", "name_ru": "Блоки питания"}, {"name": "case", "name_ru": "Корпуса"},
    {"name": "cooler", "name_ru": "Системы охлаждения"},
]
DEFAULT_STORES = [
    {"name": "DNS", "url": "https://www.dns-shop.ru"},
    {"name": "Яндекс Маркет", "url": "https://market.yandex.ru"},
    {"name": "Wildberries", "url": "https://www.wildberries.ru"},
    {"name": "Citilink", "url": "https://www.citilink.ru"},
    {"name": "Regard", "url": "https://www.regard.ru"},
]
CATEGORY_SPEC_PRIORITY = {
    "cpu": ["Сокет", "Общее количество ядер", "Количество потоков", "Базовая частота", "Максимальная частота", "Тепловыделение"],
    "gpu": ["Графический процессор", "Графический чип", "Объем видеопамяти", "Тип видеопамяти", "Интерфейс"],
    "motherboard": ["Сокет", "Чипсет", "Форм-фактор"], "ram": ["Тип памяти", "Суммарный объем", "Тактовая частота"],
    "ssd": ["Объем", "Интерфейс"], "hdd": ["Объем", "Скорость вращения"], "psu": ["Мощность"],
    "case": ["Форм-фактор"], "cooler": ["Тип", "TDP"],
}
CATEGORY_SPEC_BLOCK = {"gpu": {"Чипсет", "Сокет"}, "cpu": {"Чипсет", "Объем видеопамяти"}}

def _parse_specs(raw):
    if not raw: return {}
    if isinstance(raw, dict): return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception: return {}
    return {}

def _priority_keys_for(category):
    if category and category in CATEGORY_SPEC_PRIORITY: return CATEGORY_SPEC_PRIORITY[category]
    keys, seen = [], set()
    for lst in CATEGORY_SPEC_PRIORITY.values():
        for k in lst:
            if k not in seen: seen.add(k); keys.append(k)
    return keys

def _blocked_keys(category):
    return CATEGORY_SPEC_BLOCK.get(category or "", set())

def _match_priority_key(actual_key, priority):
    ak = actual_key.lower()
    for i, p in enumerate(priority):
        pl = p.lower()
        if ak == pl or pl in ak or ak in pl: return i
    return None

def _component_to_list_item(c):
    prices = [p for p in c.prices if p.price is not None]
    min_p = min((p.price for p in prices), default=None)
    old_p = product_url = None
    if prices:
        best = min(prices, key=lambda p: p.price if p.price is not None else 1e18)
        old_p, product_url = best.old_price, best.product_url
    return schemas.ComponentListItem(id=c.id, name=c.name, brand=c.brand, model=c.model, image_url=c.image_url,
        category_id=c.category_id, category_name=c.category.name if c.category else None, description=c.description,
        min_price=min_p, old_price=old_p, product_url=product_url, specs=_parse_specs(c.specs))

@app.get("/")
def root(): return {"message": "PC Component Comparator API", "status": "ready", "version": "0.4.1"}
@app.get("/health")
def health(): return {"status": "ok"}

@app.post("/update-database", response_model=schemas.UpdateDatabaseResponse)
async def update_database(body: Optional[schemas.UpdateDatabaseRequest] = Body(None), db: Session = Depends(get_db)):
    for cat in DEFAULT_CATEGORIES:
        if not db.query(models.Category).filter(models.Category.name == cat["name"]).first(): db.add(models.Category(**cat))
    for store in DEFAULT_STORES:
        if not db.query(models.Store).filter(models.Store.name == store["name"]).first(): db.add(models.Store(**store))
    db.commit()
    total_categories = db.query(models.Category).count()
    existing_components = db.query(models.Component).count()
    api_key = body.api_key if body else None
    economy = bool(body.economy) if body else False
    free_only = bool(body.free_only) if body else False
    yml_url = body.yml_url if body else None

    if free_only or not get_api_key(api_key):
        try:
            free_stats = await load_free_sources(db, yml_url=yml_url)
        except Exception as e:
            return schemas.UpdateDatabaseResponse(status="partial", message="Категории готовы. Бесплатная загрузка не удалась.",
                note=str(e), components_added=0, categories_ready=total_categories, economy=economy, credits_exhausted=False)
        notes = []
        for name, st in (free_stats.get("sources") or {}).items():
            if isinstance(st, dict) and st.get("error"): notes.append(f"{name}: {st['error']}")
            elif isinstance(st, dict): notes.append(f"{name}: +{st.get('components_added', 0)}")
        return schemas.UpdateDatabaseResponse(status="ok",
            message=free_stats.get("message") or f"Бесплатная подгрузка: +{free_stats.get('components_added', 0)}",
            note=(" · ".join(notes) if notes else "PCPart + GPU Ark") + ("" if free_only else " | Живые цены РФ — с ReefAPI."),
            components_added=int(free_stats.get("components_added") or 0),
            categories_ready=total_categories, economy=economy, credits_exhausted=False)

    sources = (body.sources if body and body.sources else None) or ["dns", "yandex_market", "wildberries"]
    total_added, notes, exhausted = 0, [], False
    try:
        if "dns" in sources:
            stats = await load_dns_catalog(db, max_per_query=24, pages_per_query=2, api_key=api_key, economy=economy)
            total_added += int(stats.get("components_added") or 0)
            notes.append(f"DNS: +{stats.get('components_added', 0)}")
            if stats.get("stopped_reason"): exhausted = True
        extra_sources = [s for s in sources if s in ("yandex_market", "wildberries")]
        if extra_sources and not exhausted:
            extra = await load_extra_stores(db, api_key=api_key, economy=economy, sources=extra_sources)
            total_added += int(extra.get("components_added") or 0)
            for name, st in (extra.get("sources") or {}).items():
                if isinstance(st, dict):
                    notes.append(f"{name}: +{st.get('components_added', 0)}" if "error" not in st else f"{name}: ошибка")
        if "free" in sources:
            free_stats = await load_free_sources(db, yml_url=yml_url)
            total_added += int(free_stats.get("components_added") or 0)
            notes.append(f"free: +{free_stats.get('components_added', 0)}")
    except CreditsExhaustedError as e:
        return schemas.UpdateDatabaseResponse(status="credits_exhausted", message=str(e),
            note=f"Сохранены товары ({existing_components} шт.).", components_added=total_added,
            categories_ready=total_categories, economy=economy, credits_exhausted=True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка загрузки: {e}")
    return schemas.UpdateDatabaseResponse(status="credits_exhausted" if exhausted else "ok",
        message=f"Загружено: +{total_added}.", note=" · ".join(notes) if notes else None,
        components_added=total_added, categories_ready=total_categories, economy=economy, credits_exhausted=exhausted)

@app.post("/update-database-free", response_model=schemas.UpdateDatabaseResponse)
async def update_database_free(body: Optional[schemas.UpdateDatabaseRequest] = Body(None), db: Session = Depends(get_db)):
    for cat in DEFAULT_CATEGORIES:
        if not db.query(models.Category).filter(models.Category.name == cat["name"]).first(): db.add(models.Category(**cat))
    for store in DEFAULT_STORES:
        if not db.query(models.Store).filter(models.Store.name == store["name"]).first(): db.add(models.Store(**store))
    db.commit()
    total_categories = db.query(models.Category).count()
    try:
        free_stats = await load_free_sources(db, yml_url=(body.yml_url if body else None))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    notes = []
    for name, st in (free_stats.get("sources") or {}).items():
        if isinstance(st, dict) and st.get("error"): notes.append(f"{name}: {st['error']}")
        elif isinstance(st, dict): notes.append(f"{name}: +{st.get('components_added', 0)}")
    return schemas.UpdateDatabaseResponse(status="ok",
        message=free_stats.get("message") or f"+{free_stats.get('components_added', 0)}",
        note=" · ".join(notes) if notes else "open data",
        components_added=int(free_stats.get("components_added") or 0),
        categories_ready=total_categories, economy=False, credits_exhausted=False)

@app.get("/categories", response_model=list[schemas.Category])
def list_categories(db: Session = Depends(get_db)):
    return db.query(models.Category).order_by(models.Category.id).all()

@app.get("/components", response_model=schemas.ComponentsPage)
def list_components(category: Optional[str] = Query(None), q: Optional[str] = Query(None), sort: str = Query("price_asc"),
    brand: Optional[str] = Query(None), price_min: Optional[float] = Query(None), price_max: Optional[float] = Query(None),
    spec: Optional[list[str]] = Query(None), skip: int = 0, limit: int = Query(48, le=120), db: Session = Depends(get_db)):
    query = db.query(models.Component).options(joinedload(models.Component.category), joinedload(models.Component.prices))
    if category: query = query.join(models.Category).filter(models.Category.name == category)
    if q:
        search = f"%{q}%"
        query = query.filter(or_(models.Component.name.ilike(search), models.Component.brand.ilike(search), models.Component.model.ilike(search), models.Component.description.ilike(search)))
    if brand:
        brands = [b.strip() for b in brand.split(",") if b.strip()]
        if brands: query = query.filter(or_(*[models.Component.brand.ilike(b) for b in brands]))
    components = query.all()
    filtered, spec_filters = [], []
    if spec:
        for s in spec:
            if ":" in s:
                k, v = s.split(":", 1); spec_filters.append((k.strip(), v.strip()))
    for c in components:
        prices = [p.price for p in c.prices if p.price is not None]
        min_p = min(prices) if prices else None
        if price_min is not None and (min_p is None or min_p < price_min): continue
        if price_max is not None and (min_p is None or min_p > price_max): continue
        specs = _parse_specs(c.specs)
        ok = True
        for sk, sv in spec_filters:
            matched_val = ""
            for actual_k, actual_v in specs.items():
                if actual_k == sk or sk.lower() in actual_k.lower() or actual_k.lower() in sk.lower():
                    matched_val = str(actual_v); break
            if sv.lower() not in matched_val.lower(): ok = False; break
        if ok: filtered.append(c)
    def sort_key(c):
        prices = [p.price for p in c.prices if p.price is not None]
        min_p = min(prices) if prices else None
        name = (c.name or "").lower()
        if sort == "price_desc": return (min_p is None, -(min_p or 0), name)
        if sort in ("name_asc", "name_desc"): return (name,)
        return (min_p is None, min_p or 0, name)
    if sort == "name_desc": filtered.sort(key=lambda c: (c.name or "").lower(), reverse=True)
    else: filtered.sort(key=sort_key)
    total = len(filtered)
    page = filtered[skip: skip + limit]
    return schemas.ComponentsPage(items=[_component_to_list_item(c) for c in page], total=total, skip=skip, limit=limit)

@app.get("/facets", response_model=schemas.FacetsResponse)
def get_facets(category: Optional[str] = Query(None), db: Session = Depends(get_db)):
    query = db.query(models.Component).options(joinedload(models.Component.prices))
    if category: query = query.join(models.Category).filter(models.Category.name == category)
    components = query.all()
    brand_counts, spec_counts, key_freq, prices = defaultdict(int), defaultdict(lambda: defaultdict(int)), defaultdict(int), []
    blocked, priority = _blocked_keys(category), _priority_keys_for(category)
    for c in components:
        if c.brand: brand_counts[c.brand] += 1
        for p in c.prices:
            if p.price is not None: prices.append(p.price)
        for key, val in _parse_specs(c.specs).items():
            if not val or key in blocked: continue
            key_freq[key] += 1; spec_counts[key][str(val)] += 1
    chosen, used = [], set()
    for pkey in priority:
        match = None
        for actual in key_freq:
            if actual in used or actual in blocked: continue
            if _match_priority_key(actual, [pkey]) is not None: match = actual; break
        if match: chosen.append(match); used.add(match)
    for key, _cnt in sorted(key_freq.items(), key=lambda x: -x[1]):
        if key in used or key in blocked or len(chosen) >= 8: continue
        if len(spec_counts[key]) > 40: continue
        chosen.append(key); used.add(key)
    brands = [schemas.FacetValue(value=k, count=v) for k, v in sorted(brand_counts.items(), key=lambda x: (-x[1], x[0]))]
    facets = [schemas.Facet(key=key, values=[schemas.FacetValue(value=k, count=v) for k, v in sorted((spec_counts.get(key) or {}).items(), key=lambda x: (-x[1], x[0]))[:25]]) for key in chosen if spec_counts.get(key)]
    return schemas.FacetsResponse(brands=brands[:40], specs=facets, price_min=min(prices) if prices else None, price_max=max(prices) if prices else None)

@app.get("/components/{component_id}", response_model=schemas.Component)
def get_component(component_id: int, db: Session = Depends(get_db)):
    component = db.query(models.Component).options(joinedload(models.Component.category), joinedload(models.Component.prices).joinedload(models.Price.store)).filter(models.Component.id == component_id).first()
    if not component: raise HTTPException(status_code=404, detail="Компонент не найден")
    component.specs = _parse_specs(component.specs)
    return component

@app.get("/compare")
def compare_components(ids: str = Query(...), db: Session = Depends(get_db)):
    try: id_list = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError: raise HTTPException(status_code=400, detail="Некорректный формат ids")
    if len(id_list) < 2: raise HTTPException(status_code=400, detail="Нужно минимум 2")
    if len(id_list) > 4: raise HTTPException(status_code=400, detail="Максимум 4")
    components = db.query(models.Component).options(joinedload(models.Component.category), joinedload(models.Component.prices).joinedload(models.Price.store)).filter(models.Component.id.in_(id_list)).all()
    if len(components) != len(id_list): raise HTTPException(status_code=404, detail="Не найдены")
    by_id = {c.id: c for c in components}
    ordered = [by_id[i] for i in id_list if i in by_id]
    if len({c.category_id for c in ordered}) > 1: raise HTTPException(status_code=400, detail="Разные категории")
    for c in ordered: c.specs = _parse_specs(c.specs)
    cat_name = ordered[0].category.name if ordered[0].category else None
    priority, blocked = _priority_keys_for(cat_name), _blocked_keys(cat_name)
    all_keys, seen = [], set()
    for c in ordered:
        for k in (c.specs or {}):
            if k in blocked or k in seen: continue
            seen.add(k); all_keys.append(k)
    def key_rank(k):
        m = _match_priority_key(k, priority)
        return (0, m, k.lower()) if m is not None else (1, 999, k.lower())
    all_keys.sort(key=key_rank)
    return {"category": cat_name, "category_ru": ordered[0].category.name_ru if ordered[0].category else None, "spec_keys": all_keys, "components": ordered}

@app.get("/catalog/export")
def export_catalog(db: Session = Depends(get_db)):
    components = db.query(models.Component).options(joinedload(models.Component.category), joinedload(models.Component.prices).joinedload(models.Price.store)).all()
    items = []
    for c in components:
        prices = [p for p in c.prices if p.price is not None]
        best = min(prices, key=lambda p: p.price) if prices else None
        items.append({"category": c.category.name if c.category else "cpu", "name": c.name, "brand": c.brand, "description": c.description, "image_url": c.image_url, "specs": _parse_specs(c.specs), "price": best.price if best else None, "old_price": best.old_price if best else None, "product_url": best.product_url if best else None, "external_id": best.external_id if best else None, "store": best.store.name if best and best.store else "DNS"})
    return {"count": len(items), "items": items}

@app.post("/catalog/import")
def import_catalog(body: schemas.CatalogImportRequest, db: Session = Depends(get_db)):
    for cat in DEFAULT_CATEGORIES:
        if not db.query(models.Category).filter(models.Category.name == cat["name"]).first(): db.add(models.Category(**cat))
    for store in DEFAULT_STORES:
        if not db.query(models.Store).filter(models.Store.name == store["name"]).first(): db.add(models.Store(**store))
    db.commit()
    cats = {c.name: c for c in db.query(models.Category).all()}
    stores = {s.name: s for s in db.query(models.Store).all()}
    added = updated = 0
    for item in body.items:
        cat = cats.get(item.category)
        if not cat: continue
        store = stores.get(item.store) or stores.get("DNS")
        if not store: continue
        external_id = item.external_id or f"import-{item.category}-{item.name}"[:120]
        existing_price = db.query(models.Price).filter(models.Price.store_id == store.id, models.Price.external_id == str(external_id)).first()
        specs_json = json.dumps(item.specs, ensure_ascii=False) if item.specs else None
        if existing_price:
            comp = existing_price.component
            comp.name, comp.brand, comp.description = item.name, item.brand, item.description
            comp.image_url = item.image_url or comp.image_url
            if specs_json: comp.specs = specs_json
            if item.price is not None: existing_price.price = float(item.price)
            if item.old_price is not None: existing_price.old_price = float(item.old_price)
            existing_price.product_url = item.product_url; updated += 1; continue
        comp = models.Component(category_id=cat.id, name=item.name, brand=item.brand, description=item.description, image_url=item.image_url, specs=specs_json)
        db.add(comp); db.flush()
        db.add(models.Price(component_id=comp.id, store_id=store.id, price=float(item.price) if item.price is not None else None, old_price=float(item.old_price) if item.old_price is not None else None, in_stock=True, product_url=item.product_url, external_id=str(external_id)))
        added += 1
    db.commit()
    return {"status": "ok", "added": added, "updated": updated, "message": f"Импорт: +{added}, обновлено {updated}"}
