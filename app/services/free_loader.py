"""
Бесплатная подгрузка БЕЗ API-ключа ReefAPI.

Источники:
1) docyx/pc-part-dataset (GitHub) — характеристики + ориентир. цена USD
2) GPU Ark free REST — спеки GPU
3) Пользовательский YML-фид

После загрузки: двустороннее обогащение (free ↔ API) картинками и спеками;
поиск картинок в Wikimedia/Openverse; SVG-заглушка если ничего не найдено.
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

USD_TO_RUB = 90.0
PCPART_BASE = "https://raw.githubusercontent.com/docyx/pc-part-dataset/main/data/json"

PCPART_FILES: dict[str, str] = {
    "cpu": "cpu.json",
    "gpu": "video-card.json",
    "motherboard": "motherboard.json",
    "ram": "memory.json",
    "ssd": "internal-hard-drive.json",
    "hdd": "internal-hard-drive.json",
    "psu": "power-supply.json",
    "case": "case.json",
    "cooler": "cpu-cooler.json",
}

GPUARK_BASE = "https://gpuark.com/api/v1"

HEADERS = {
    "User-Agent": "PCComparator/0.4.3 (+https://github.com/DoctorGreeb/pc-component-comparator)",
    "Accept": "application/json, application/xml, text/xml, */*",
}

_STOP = {
    "the", "and", "for", "with", "black", "white", "rgb", "oc", "gaming",
    "edition", "series", "pci", "pcie", "box", "oem", "tray", "rtl",
}


def _norm_name(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^\wа-яё]+", " ", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s: str) -> set[str]:
    return {t for t in _norm_name(s).split() if len(t) > 1 and t not in _STOP}


def _name_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    union = ta | tb
    jaccard = len(inter) / len(union)
    models_a = {t for t in ta if re.search(r"\d", t) and len(t) >= 3}
    models_b = {t for t in tb if re.search(r"\d", t) and len(t) >= 3}
    model_bonus = 0.25 if models_a and models_a & models_b else 0.0
    return min(1.0, jaccard + model_bonus)


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


def _fmt(val: Any) -> str | None:
    if val is None or val == "":
        return None
    if isinstance(val, bool):
        return "да" if val else "нет"
    if isinstance(val, float):
        return str(int(val)) if val == int(val) else str(val)
    return str(val)


def _ensure_store(db: Session, name: str, url: str) -> models.Store:
    store = db.query(models.Store).filter(models.Store.name == name).first()
    if not store:
        store = models.Store(name=name, url=url)
        db.add(store)
        db.flush()
    return store


def _find_donor(
    db: Session,
    *,
    category_id: int,
    name: str,
    exclude_id: int | None = None,
    need_image: bool = True,
    need_specs: bool = True,
) -> models.Component | None:
    candidates = (
        db.query(models.Component)
        .filter(models.Component.category_id == category_id)
        .all()
    )
    best: models.Component | None = None
    best_score = 0.45
    for c in candidates:
        if exclude_id and c.id == exclude_id:
            continue
        if need_image and not c.image_url:
            continue
        if need_specs and not _parse_specs(c.specs):
            if not need_image:
                continue
        score = _name_similarity(name, c.name or "")
        if score > best_score:
            best_score = score
            best = c
    return best


def _merge_specs(base: dict | None, donor: dict | None) -> dict:
    out = dict(base or {})
    for k, v in (donor or {}).items():
        if k not in out or not out[k]:
            out[k] = v
    return out


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
    if not image_url:
        donor = _find_donor(
            db, category_id=category.id, name=name, need_image=True, need_specs=False
        )
        if donor and donor.image_url:
            image_url = donor.image_url
            donor_specs = _parse_specs(donor.specs)
            if donor_specs:
                specs = _merge_specs(specs, donor_specs)
            if not brand and donor.brand:
                brand = donor.brand
    elif not specs or len(specs) < 2:
        donor = _find_donor(
            db, category_id=category.id, name=name, need_image=False, need_specs=True
        )
        if donor:
            specs = _merge_specs(specs, _parse_specs(donor.specs))

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
            old = _parse_specs(comp.specs)
            merged = _merge_specs(old, specs)
            comp.specs = json.dumps(merged, ensure_ascii=False)
        if image_url and not comp.image_url:
            comp.image_url = image_url
        elif image_url and comp.image_url and "placeholder" in (comp.image_url or ""):
            comp.image_url = image_url
        if description:
            comp.description = description
        if price is not None:
            existing.price = float(price)
        existing.product_url = product_url or existing.product_url
        return False

    similar = _find_donor(
        db, category_id=category.id, name=name, need_image=False, need_specs=False
    )
    if similar and _name_similarity(name, similar.name or "") >= 0.75:
        comp = similar
        if image_url and not comp.image_url:
            comp.image_url = image_url
        if specs:
            merged = _merge_specs(_parse_specs(comp.specs), specs)
            comp.specs = json.dumps(merged, ensure_ascii=False)
        if brand and not comp.brand:
            comp.brand = brand
    else:
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
    mapping = [
        ("core_count", "Общее количество ядер", None),
        ("core_clock", "Базовая частота", " GHz"),
        ("boost_clock", "Максимальная частота", " GHz"),
        ("tdp", "Тепловыделение", " Вт"),
        ("microarchitecture", "Архитектура", None),
        ("graphics", "Графика", None),
        ("smt", "Многопоточность", None),
    ]
    for key, label, suffix in mapping:
        v = _fmt(item.get(key))
        if v is not None:
            out[label] = f"{v}{suffix or ''}"
    return out


def _gpu_specs(item: dict) -> dict:
    out = {}
    if item.get("chipset") is not None:
        out["Графический чип"] = str(item["chipset"])
    mem = item.get("memory")
    if mem is not None:
        out["Объем видеопамяти"] = f"{mem} ГБ" if isinstance(mem, (int, float)) else str(mem)
    if item.get("memory_type"):
        out["Тип видеопамяти"] = str(item["memory_type"])
    if item.get("core_clock") is not None:
        out["Частота видеочипа"] = f"{item['core_clock']} МГц"
    if item.get("boost_clock") is not None:
        out["Boost частота"] = f"{item['boost_clock']} МГц"
    if item.get("color") is not None:
        out["Цвет"] = str(item["color"])
    if item.get("length") is not None:
        out["Длина видеокарты"] = f"{item['length']} мм"
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
        try:
            out["Суммарный объем"] = f"{int(modules[0]) * int(modules[1])} ГБ"
        except Exception:
            pass
    if item.get("cas_latency") is not None:
        out["Тайминги"] = f"CL{item['cas_latency']}"
    if item.get("first_word_latency") is not None:
        out["First Word Latency"] = f"{item['first_word_latency']} нс"
    if item.get("color") is not None:
        out["Цвет"] = str(item["color"])
    return out


def _mb_specs(item: dict) -> dict:
    out = {}
    for k, label, suf in [
        ("socket", "Сокет", None),
        ("form_factor", "Форм-фактор", None),
        ("chipset", "Чипсет", None),
        ("memory_max", "Максимальный объем памяти", " ГБ"),
        ("memory_slots", "Количество слотов памяти", None),
        ("color", "Цвет", None),
        ("memory_type", "Тип поддерживаемой памяти", None),
    ]:
        v = _fmt(item.get(k))
        if v is not None:
            out[label] = f"{v}{suf or ''}"
    return out


def _storage_specs(item: dict) -> dict:
    out = {}
    if item.get("capacity") is not None:
        cap = item["capacity"]
        try:
            cap_i = int(cap)
            out["Объем"] = f"{cap_i} ГБ" if cap_i < 1000 else f"{cap_i / 1000:g} ТБ"
        except Exception:
            out["Объем"] = str(cap)
    for k, label in [
        ("type", "Тип"),
        ("form_factor", "Форм-фактор"),
        ("interface", "Интерфейс"),
        ("cache", "Кэш-память"),
    ]:
        v = _fmt(item.get(k))
        if v is not None:
            out[label] = v
    return out


def _psu_specs(item: dict) -> dict:
    out = {}
    if item.get("wattage") is not None:
        out["Мощность"] = f"{item['wattage']} Вт"
    for k, label in [
        ("efficiency", "Сертификат 80 PLUS"),
        ("modular", "Модульность"),
        ("type", "Форм-фактор"),
        ("color", "Цвет"),
    ]:
        v = _fmt(item.get(k))
        if v is not None:
            out[label] = v
    return out


def _case_specs(item: dict) -> dict:
    out = {}
    for k, label in [
        ("type", "Форм-фактор"),
        ("color", "Цвет"),
        ("side_panel", "Боковая панель"),
        ("external_volume", "Объем"),
        ("motherboard_form_factor", "Поддерживаемые форм-факторы плат"),
    ]:
        v = _fmt(item.get(k))
        if v is not None:
            out[label] = v
    return out


def _cooler_specs(item: dict) -> dict:
    out = {}
    if item.get("rpm") is not None:
        out["Обороты"] = str(item["rpm"])
    if item.get("noise_level") is not None:
        out["Шум"] = str(item["noise_level"])
    if item.get("size") is not None:
        out["Размер радиатора"] = str(item["size"])
    if item.get("color") is not None:
        out["Цвет"] = str(item["color"])
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


async def enrich_missing_media(db: Session, *, web_images: bool = True, max_web: int = 80) -> dict[str, int]:
    """
    1) Доноры в той же категории (free ↔ API): картинки и спеки.
    2) Без картинки — Wikimedia / Openverse.
    3) Иначе SVG-заглушка (ни один товар без image_url).
    """
    from app.services.image_enrichment import find_image_url, placeholder_data_uri

    components = db.query(models.Component).all()
    cats = {c.id: c.name for c in db.query(models.Category).all()}
    by_cat: dict[int, list[models.Component]] = {}
    for c in components:
        by_cat.setdefault(c.category_id, []).append(c)

    images_filled = 0
    specs_filled = 0
    web_filled = 0
    placeholder_filled = 0

    for cat_id, group in by_cat.items():
        donors_img = [c for c in group if c.image_url and not str(c.image_url).startswith("data:")]
        donors_spec = [c for c in group if len(_parse_specs(c.specs)) >= 2]

        for c in group:
            if not c.image_url and donors_img:
                best, best_s = None, 0.5
                for d in donors_img:
                    if d.id == c.id:
                        continue
                    s = _name_similarity(c.name or "", d.name or "")
                    if s > best_s:
                        best_s, best = s, d
                if best and best.image_url:
                    c.image_url = best.image_url
                    images_filled += 1
                    if len(_parse_specs(c.specs)) < 2:
                        ds = _parse_specs(best.specs)
                        if ds:
                            c.specs = json.dumps(ds, ensure_ascii=False)
                            specs_filled += 1

            cur = _parse_specs(c.specs)
            if donors_spec:
                best, best_s = None, 0.5
                for d in donors_spec:
                    if d.id == c.id:
                        continue
                    s = _name_similarity(c.name or "", d.name or "")
                    if s > best_s:
                        best_s, best = s, d
                if best:
                    merged = _merge_specs(cur, _parse_specs(best.specs))
                    if len(merged) > len(cur):
                        c.specs = json.dumps(merged, ensure_ascii=False)
                        specs_filled += 1
                        cur = merged
                    if not c.image_url and best.image_url and not str(best.image_url).startswith("data:"):
                        c.image_url = best.image_url
                        images_filled += 1

    db.commit()

    if web_images:
        need = [c for c in db.query(models.Component).all() if not c.image_url][:max_web]
        async with httpx.AsyncClient(
            timeout=25.0,
            headers={
                "User-Agent": "PCComparator/0.4.3 (+https://github.com/DoctorGreeb/pc-component-comparator)",
                "Accept": "application/json",
            },
            follow_redirects=True,
        ) as client:
            for c in need:
                cat_name = cats.get(c.category_id)
                try:
                    url = await find_image_url(c.name or "", category=cat_name, client=client)
                except Exception:
                    url = None
                if url:
                    c.image_url = url
                    web_filled += 1
                else:
                    c.image_url = placeholder_data_uri(cat_name)
                    placeholder_filled += 1
        db.commit()

    left = (
        db.query(models.Component)
        .filter((models.Component.image_url == None) | (models.Component.image_url == ""))  # noqa: E711
        .all()
    )
    for c in left:
        c.image_url = placeholder_data_uri(cats.get(c.category_id))
        placeholder_filled += 1
    if left:
        db.commit()

    return {
        "images_filled": images_filled,
        "specs_filled": specs_filled,
        "web_filled": web_filled,
        "placeholder_filled": placeholder_filled,
    }


async def load_pcpart_dataset(db: Session, limit_per_cat: int = 120) -> dict[str, Any]:
    categories = {c.name: c for c in db.query(models.Category).all()}
    store = _ensure_store(
        db, "PCPartPicker dataset", "https://github.com/docyx/pc-part-dataset"
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

                specs = builder(item)
                if not specs:
                    for k, v in item.items():
                        if k in ("name", "price", "price_per_gb") or v is None:
                            continue
                        if isinstance(v, (str, int, float, bool)):
                            specs[k] = str(v)

                ext = f"pcp-{cat_name}-{re.sub(r'[^a-zA-Z0-9]+', '-', name)[:80].lower()}"
                if _upsert(
                    db,
                    category=cat,
                    store=store,
                    name=name,
                    brand=_extract_brand(name),
                    external_id=ext,
                    price=price_rub,
                    specs=specs,
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
        "note": f"Цены ≈ USD×{USD_TO_RUB} (ориентир)",
    }


async def load_gpu_ark(db: Session, pages: int = 8, per_page: int = 50) -> dict[str, Any]:
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
                if item.get("vendor"):
                    specs["Производитель"] = str(item["vendor"])
                if item.get("card_release_date"):
                    specs["Дата выхода"] = str(item["card_release_date"])

                slug = item.get("slug")
                image_url = None
                if slug:
                    try:
                        dresp = await client.get(f"{GPUARK_BASE}/gpus/{slug}/")
                        if dresp.status_code == 200:
                            detail = dresp.json()
                            if isinstance(detail, dict):
                                for k, label in [
                                    ("tdp", "TDP"),
                                    ("bus_width", "Разрядность шины памяти"),
                                    ("memory_bus", "Разрядность шины памяти"),
                                    ("boost_clock", "Boost частота"),
                                    ("base_clock", "Частота видеочипа"),
                                ]:
                                    if detail.get(k) is not None and label not in specs:
                                        specs[label] = str(detail[k])
                                image_url = (
                                    detail.get("image")
                                    or detail.get("image_url")
                                    or detail.get("photo")
                                )
                    except Exception:
                        pass

                if _upsert(
                    db,
                    category=cat,
                    store=store,
                    name=name,
                    brand=item.get("vendor") or item.get("manufacturer"),
                    external_id=f"gpuark-{slug or name}"[:120],
                    price=None,
                    specs=specs,
                    image_url=image_url,
                    product_url=item.get("url"),
                    description="Спецификации GPU Ark",
                ):
                    added += 1
            db.commit()

    return {"source": "gpu_ark", "components_added": added}


def _yml_local(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


async def load_yml_feed(db: Session, feed_url: str, limit: int = 300) -> dict[str, Any]:
    parsed = urlparse(feed_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Нужен http(s) URL фида")

    categories = {c.name: c for c in db.query(models.Category).all()}
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

    store = _ensure_store(db, f"YML:{parsed.netloc or 'feed'}"[:80], feed_url)

    async with httpx.AsyncClient(timeout=120.0, headers=HEADERS, follow_redirects=True) as client:
        resp = await client.get(feed_url)
        resp.raise_for_status()
        text = resp.text

    text = re.sub(r'xmlns(:\w+)?="[^"]*"', "", text)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"Некорректный XML/YML: {e}") from e

    offers = [el for el in root.iter() if _yml_local(el.tag) == "offer"]
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
            elif tag == "picture" and not picture:
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
    limit_per_cat: int = 120,
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

    try:
        enrich = await enrich_missing_media(db, web_images=True, max_web=100)
        results["sources"]["enrichment"] = enrich
    except Exception as e:
        results["sources"]["enrichment"] = {"error": str(e)}

    results["components_added"] = total
    enrich_note = results["sources"].get("enrichment") or {}
    results["message"] = (
        f"Бесплатная подгрузка: +{total}. "
        f"Доноры: img {enrich_note.get('images_filled', 0)}, "
        f"спеки {enrich_note.get('specs_filled', 0)}; "
        f"web {enrich_note.get('web_filled', 0)}, "
        f"заглушки {enrich_note.get('placeholder_filled', 0)}. "
        "Цены open-data — ориентир (USD→RUB)."
    )
    return results
