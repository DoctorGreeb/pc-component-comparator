"""
Бесплатная подгрузка БЕЗ API-ключа ReefAPI.

Легальные источники:
1) docyx/pc-part-dataset (публичный JSON на GitHub, характеристики + ориентир. цена USD)
2) GPU Ark free REST API (https://gpuark.com/api) — без ключа, только GPU-спеки
3) Пользовательский YML-фид (URL) — магазин сам публикует фид для Маркета/Директа

Не используем обход антибота DNS/Citilink — это не легальная альтернатива.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app import models
from app.services.dns_loader import _extract_brand

# Ориентировочный курс для отображения USD→RUB (датасет PCPartPicker в долларах)
USD_TO_RUB = 90.0

PCPART_BASE = "https://raw.githubusercontent.com/docyx/pc-part-dataset/main/data/json"

# category name в нашей БД → файл датасета
PCPART_FILES: dict[str, str] = {
    "cpu": "cpu.json",
    "gpu": "video-card.json",
    "motherboard": "motherboard.json",
    "ram": "memory.json",
    "ssd": "internal-hard-drive.json",  # фильтруем SSD
    "hdd": "internal-hard-drive.json",  # фильтруем HDD
    "psu": "power-supply.json",
    "case": "case.json",
    "cooler": "cpu-cooler.json",
}

GPUARK_BASE = "https://gpuark.com/api/v1"

HEADERS = {
    "User-Agent": "PCComparator/0.4 (+https://github.com/DoctorGreeb/pc-component-comparator; free open-data loader)",
    "Accept": "application/json, application/xml, text/xml, */*",
}


def _ensure_store(db: Session, name: str, url: str) -> models.Store:
    store = db.query(models.Store).filter(models.Store.name == name).first()
    if not store:
        store = models.Store(name=name, url=url)
        db.add(store)
        db.flush()
    return store


def _upsert(
    db: Session,
    *,
    category: models.Category,
    store: models.Store,
    name: str,
    brand: str | None,
    external_id: str,
    price: float | None,
    specs: dict | None,
    image_url: str | None = None,
    product_url: str | None = None,
    description: str | None = None,
) -> bool:
    existing = (
        db.query(models.Price)
        .filter(models.Price.store_id == store.id, models.Price.external_id == external_id)
        .first()
    )
    specs_json = json.dumps(specs, ensure_ascii=False) if specs else None
    if existing:
        comp = existing.component
        comp.name = name
        if brand:
            comp.brand = brand
        if specs_json:
            comp.specs = specs_json
        if image_url:
            comp.image_url = image_url or comp.image_url
        if description:
            comp.description = description
        if price is not None:
            existing.price = float(price)
        existing.product_url = product_url or existing.product_url
        return False

    comp = models.Component(
        category_id=category.id,
        name=name,
        brand=brand or _extract_brand(name),
        description=description,
        image_url=image_url,
        specs=specs_json,
    )
    db.add(comp)
    db.flush()
    db.add(
        models.Price(
            component_id=comp.id,
            store_id=store.id,
            price=float(price) if price is not None else None,
            old_price=None,
            in_stock=True,
            product_url=product_url,
            external_id=external_id,
        )
    )
    return True


def _cpu_specs(item: dict) -> dict:
    out = {}
    if item.get("core_count") is not None:
        out["Общее количество ядер"] = str(item["core_count"])
    if item.get("core_clock") is not None:
        out["Базовая частота"] = f"{item['core_clock']} GHz"
    if item.get("boost_clock") is not None:
        out["Максимальная частота"] = f"{item['boost_clock']} GHz"
    if item.get("tdp") is not None:
        out["Тепловыделение"] = f"{item['tdp']} Вт"
    if item.get("microarchitecture"):
        out["Архитектура"] = str(item["microarchitecture"])
    if item.get("graphics"):
        out["Графика"] = str(item["graphics"])
    return out


def _gpu_specs(item: dict) -> dict:
    out = {}
    for k, label in [
        ("chipset", "Графический чип"),
        ("memory", "Объем видеопамяти"),
        ("memory_type", "Тип видеопамяти"),
        ("core_clock", "Частота видеочипа"),
        ("boost_clock", "Boost частота"),
        ("color", "Цвет"),
        ("length", "Длина видеокарты"),
    ]:
        if item.get(k) is not None:
            out[label] = str(item[k])
    return out


def _ram_specs(item: dict) -> dict:
    out = {}
    speed = item.get("speed")
    if isinstance(speed, list) and len(speed) >= 2:
        out["Тип памяти"] = f"DDR{speed[0]}"
        out["Тактовая частота"] = f"{speed[1]} МГц"
    modules = item.get("modules")
    if isinstance(modules, list) and len(modules) >= 2:
        out["Количество модулей"] = str(modules[0])
        out["Объем одного модуля"] = f"{modules[1]} ГБ"
        out["Суммарный объем"] = f"{modules[0] * modules[1]} ГБ"
    if item.get("cas_latency") is not None:
        out["Тайминги"] = f"CL{item['cas_latency']}"
    return out


def _mb_specs(item: dict) -> dict:
    out = {}
    for k, label in [
        ("socket", "Сокет"),
        ("form_factor", "Форм-фактор"),
        ("chipset", "Чипсет"),
        ("memory_max", "Максимальный объем памяти"),
        ("memory_slots", "Количество слотов памяти"),
        ("color", "Цвет"),
    ]:
        if item.get(k) is not None:
            out[label] = str(item[k])
    return out


def _storage_specs(item: dict) -> dict:
    out = {}
    if item.get("capacity") is not None:
        out["Объем"] = f"{item['capacity']} ГБ"
    if item.get("type") is not None:
        out["Тип"] = str(item["type"])
    if item.get("form_factor") is not None:
        out["Форм-фактор"] = str(item["form_factor"])
    if item.get("interface") is not None:
        out["Интерфейс"] = str(item["interface"])
    if item.get("cache") is not None:
        out["Кэш-память"] = str(item["cache"])
    return out


def _psu_specs(item: dict) -> dict:
    out = {}
    for k, label in [
        ("wattage", "Мощность"),
        ("efficiency", "Сертификат 80 PLUS"),
        ("modular", "Модульность"),
        ("type", "Форм-фактор"),
    ]:
        if item.get(k) is not None:
            out[label] = str(item[k])
    return out


def _case_specs(item: dict) -> dict:
    out = {}
    for k, label in [
        ("type", "Форм-фактор"),
        ("color", "Цвет"),
        ("side_panel", "Боковая панель"),
        ("external_volume", "Объем"),
    ]:
        if item.get(k) is not None:
            out[label] = str(item[k])
    return out


def _cooler_specs(item: dict) -> dict:
    out = {}
    if item.get("rpm") is not None:
        out["Обороты"] = str(item["rpm"])
    if item.get("noise_level") is not None:
        out["Шум"] = str(item["noise_level"])
    if item.get("size") is not None:
        out["Размер радиатора"] = str(item["size"])
    return out


SPEC_BUILDERS = {
    "cpu": _cpu_specs,
    "gpu": _gpu_specs,
    "ram": _ram_specs,
    "motherboard": _mb_specs,
    "ssd": _storage_specs,
    "hdd": _storage_specs,
    "psu": _psu_specs,
    "case": _case_specs,
    "cooler": _cooler_specs,
}


async def load_pcpart_dataset(db: Session, limit_per_cat: int = 80) -> dict[str, Any]:
    categories = {c.name: c for c in db.query(models.Category).all()}
    store = _ensure_store(
        db,
        "PCPartPicker dataset",
        "https://github.com/docyx/pc-part-dataset",
    )
    added = 0
    loaded_cats = 0

    async with httpx.AsyncClient(timeout=120.0, headers=HEADERS) as client:
        for cat_name, filename in PCPART_FILES.items():
            cat = categories.get(cat_name)
            if not cat:
                continue
            url = f"{PCPART_BASE}/{filename}"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                items = resp.json()
            except Exception as e:
                return {"error": f"{cat_name}: {e}", "components_added": added}

            if not isinstance(items, list):
                continue

            builder = SPEC_BUILDERS.get(cat_name, lambda x: {})
            count = 0
            for item in items:
                if count >= limit_per_cat:
                    break
                name = item.get("name") or ""
                if not name:
                    continue

                # SSD/HDD фильтр по type
                if cat_name == "ssd":
                    t = str(item.get("type") or "").lower()
                    if t and t != "ssd" and "ssd" not in t:
                        continue
                if cat_name == "hdd":
                    t = str(item.get("type") or "").lower()
                    if t == "ssd" or "ssd" in t:
                        continue

                price_usd = item.get("price")
                price_rub = None
                if isinstance(price_usd, (int, float)) and price_usd > 0:
                    price_rub = round(float(price_usd) * USD_TO_RUB, 2)

                ext = f"pcp-{cat_name}-{re.sub(r'[^a-zA-Z0-9]+', '-', name)[:80].lower()}"
                if _upsert(
                    db,
                    category=cat,
                    store=store,
                    name=name,
                    brand=_extract_brand(name),
                    external_id=ext,
                    price=price_rub,
                    specs=builder(item),
                    description="Ориентир. цена из открытого датасета PCPartPicker (USD→RUB)",
                ):
                    added += 1
                count += 1
            loaded_cats += 1
            db.commit()

    return {
        "source": "pcpart_dataset",
        "components_added": added,
        "categories": loaded_cats,
        "note": f"Цены ≈ USD×{USD_TO_RUB} (ориентир, не витрина РФ)",
    }


async def load_gpu_ark(db: Session, pages: int = 5, per_page: int = 50) -> dict[str, Any]:
    """Спеки GPU с gpuark.com — бесплатный API без ключа."""
    categories = {c.name: c for c in db.query(models.Category).all()}
    cat = categories.get("gpu")
    if not cat:
        return {"components_added": 0, "error": "нет категории gpu"}

    store = _ensure_store(db, "GPU Ark", "https://gpuark.com")
    added = 0

    async with httpx.AsyncClient(timeout=60.0, headers=HEADERS) as client:
        for page in range(1, pages + 1):
            try:
                resp = await client.get(
                    f"{GPUARK_BASE}/gpus/",
                    params={"page": page, "per_page": per_page, "sort": "-gpi"},
                )
                resp.raise_for_status()
                body = resp.json()
            except Exception as e:
                return {"components_added": added, "error": str(e)}

            results = body.get("results") or []
            if not results:
                break
            for item in results:
                name = item.get("name") or ""
                if not name:
                    continue
                # потребительские карты
                low = name.lower()
                if not any(x in low for x in ("geforce", "radeon", "rtx", "rx ", "arc ")):
                    continue
                specs = {}
                if item.get("ram") is not None:
                    specs["Объем видеопамяти"] = f"{item['ram']} {item.get('ram_unit') or 'GB'}"
                if item.get("ram_type"):
                    specs["Тип видеопамяти"] = str(item["ram_type"])
                if item.get("cores") is not None:
                    specs["Ядра"] = str(item["cores"])
                if item.get("fp32_performance") is not None:
                    specs["FP32 TFLOPS"] = str(item["fp32_performance"])
                slug = item.get("slug") or name
                if _upsert(
                    db,
                    category=cat,
                    store=store,
                    name=name,
                    brand=item.get("vendor") or item.get("manufacturer"),
                    external_id=f"gpuark-{slug}"[:120],
                    price=None,
                    specs=specs,
                    product_url=item.get("url"),
                    description="Спецификации GPU Ark (без цены)",
                ):
                    added += 1
            db.commit()

    return {"source": "gpu_ark", "components_added": added}


def _yml_local(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


async def load_yml_feed(db: Session, feed_url: str, limit: int = 300) -> dict[str, Any]:
    """Импорт публичного YML-фида магазина (легально, если URL открыт)."""
    parsed = urlparse(feed_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Нужен http(s) URL фида")

    categories = {c.name: c for c in db.query(models.Category).all()}
    # эвристика категории по тексту
    KEYWORDS = {
        "cpu": ["процессор", "cpu", "ryzen", "core i"],
        "gpu": ["видеокарта", "geforce", "radeon", "rtx", "rx "],
        "motherboard": ["материнск", "motherboard"],
        "ram": ["оперативн", "ddr4", "ddr5", "память dimm"],
        "ssd": ["ssd", "nvme", "накопител"],
        "hdd": ["жесткий диск", "hdd"],
        "psu": ["блок питания", "power supply"],
        "case": ["корпус"],
        "cooler": ["кулер", "охлажден", "сво "],
    }

    store_name = parsed.netloc or "YML feed"
    store = _ensure_store(db, f"YML:{store_name}"[:80], feed_url)

    async with httpx.AsyncClient(timeout=120.0, headers=HEADERS, follow_redirects=True) as client:
        resp = await client.get(feed_url)
        resp.raise_for_status()
        text = resp.text

    # убираем namespace если есть
    text = re.sub(r"xmlns(:\w+)?=\"[^\"]*\"", "", text)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"Некорректный XML/YML: {e}") from e

    offers = []
    for el in root.iter():
        if _yml_local(el.tag) == "offer":
            offers.append(el)

    added = 0
    for offer in offers[:limit]:
        oid = offer.attrib.get("id") or ""
        name = price = url = picture = None
        params: dict[str, str] = {}
        for child in list(offer):
            tag = _yml_local(child.tag)
            if tag == "name":
                name = (child.text or "").strip()
            elif tag == "price":
                try:
                    price = float((child.text or "0").replace(",", "."))
                except ValueError:
                    price = None
            elif tag == "url":
                url = (child.text or "").strip()
            elif tag == "picture":
                picture = (child.text or "").strip()
            elif tag == "param":
                pname = child.attrib.get("name") or ""
                if pname and child.text:
                    params[pname] = child.text.strip()
        if not name:
            continue

        low = name.lower()
        cat_name = None
        for cn, kws in KEYWORDS.items():
            if any(k in low for k in kws):
                cat_name = cn
                break
        if not cat_name or cat_name not in categories:
            continue

        ext = f"yml-{oid or re.sub(r'[^a-zA-Z0-9]+', '-', name)[:60]}"
        if _upsert(
            db,
            category=categories[cat_name],
            store=store,
            name=name,
            brand=_extract_brand(name),
            external_id=ext[:120],
            price=price,
            specs=params or None,
            image_url=picture,
            product_url=url,
        ):
            added += 1
    db.commit()
    return {"source": "yml_feed", "components_added": added, "offers_seen": len(offers)}


async def load_free_sources(
    db: Session,
    *,
    yml_url: str | None = None,
    limit_per_cat: int = 80,
) -> dict[str, Any]:
    results: dict[str, Any] = {"sources": {}}
    total = 0

    try:
        r1 = await load_pcpart_dataset(db, limit_per_cat=limit_per_cat)
        results["sources"]["pcpart_dataset"] = r1
        total += int(r1.get("components_added") or 0)
    except Exception as e:
        results["sources"]["pcpart_dataset"] = {"error": str(e)}

    try:
        r2 = await load_gpu_ark(db)
        results["sources"]["gpu_ark"] = r2
        total += int(r2.get("components_added") or 0)
    except Exception as e:
        results["sources"]["gpu_ark"] = {"error": str(e)}

    if yml_url and yml_url.strip():
        try:
            r3 = await load_yml_feed(db, yml_url.strip())
            results["sources"]["yml_feed"] = r3
            total += int(r3.get("components_added") or 0)
        except Exception as e:
            results["sources"]["yml_feed"] = {"error": str(e)}

    results["components_added"] = total
    results["message"] = (
        f"Бесплатная подгрузка: +{total}. "
        "Цены из открытого датасета — ориентир (USD→RUB), не витрина DNS."
    )
    return results
