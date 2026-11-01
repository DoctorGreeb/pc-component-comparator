"""Обогащение картинок/спеков + web-поиск с таймаутом."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app import models
from app.services.image_enrichment import (
    find_image_url,
    is_placeholder_url,
    placeholder_data_uri,
)

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


def _merge_specs(base: dict | None, donor: dict | None) -> dict:
    out = dict(base or {})
    for k, v in (donor or {}).items():
        if k not in out or not out[k]:
            out[k] = v
    return out


async def enrich_missing_media(
    db: Session,
    *,
    web_images: bool = True,
    max_web: int = 80,
    image_timeout_sec: float = 8.0,
    google_api_key: str | None = None,
    google_cx: str | None = None,
    on_progress=None,
) -> dict[str, int]:
    async def _prog(msg: str, pct: float | None = None):
        if on_progress is None:
            return
        try:
            r = on_progress(msg, pct)
            if hasattr(r, "__await__"):
                await r
        except Exception:
            pass

    components = db.query(models.Component).all()
    cats = {c.id: c.name for c in db.query(models.Category).all()}
    by_cat: dict[int, list[models.Component]] = {}
    for c in components:
        by_cat.setdefault(c.category_id, []).append(c)

    images_filled = 0
    specs_filled = 0
    web_filled = 0
    placeholder_filled = 0
    timeouts = 0
    placeholders_replaced = 0
    await _prog("Сверка доноров: копирование спеков и картинок между похожими товарами…")

    for cat_id, group in by_cat.items():
        donors_img = [
            c for c in group
            if c.image_url and not is_placeholder_url(c.image_url)
        ]
        donors_spec = [c for c in group if len(_parse_specs(c.specs)) >= 2]

        for c in group:
            if is_placeholder_url(c.image_url) and donors_img:
                best, best_s = None, 0.5
                for d in donors_img:
                    if d.id == c.id:
                        continue
                    s = _name_similarity(c.name or "", d.name or "")
                    if s > best_s:
                        best_s, best = s, d
                if best and best.image_url and not is_placeholder_url(best.image_url):
                    was_ph = is_placeholder_url(c.image_url)
                    c.image_url = best.image_url
                    images_filled += 1
                    if was_ph:
                        placeholders_replaced += 1
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
                    if is_placeholder_url(c.image_url) and best.image_url and not is_placeholder_url(best.image_url):
                        c.image_url = best.image_url
                        images_filled += 1
                        placeholders_replaced += 1

    db.commit()

    if web_images:
        need = [
            c for c in db.query(models.Component).all()
            if is_placeholder_url(c.image_url)
        ][:max_web]
        timeout = max(2.5, min(20.0, float(image_timeout_sec or 8)))
        await _prog(
            f"Поиск картинок (Google/DDG/Bing/Wiki): "
            f"{len(need)} без фото или с заглушкой, таймаут {timeout:.0f} с…"
        )
        async with httpx.AsyncClient(
            timeout=min(timeout + 1, 12.0),
            headers={
                "User-Agent": "PCComparator/0.4.8 (+https://github.com/DoctorGreeb/pc-component-comparator)",
                "Accept": "application/json, text/html, */*",
            },
            follow_redirects=True,
        ) as client:
            for i, c in enumerate(need, 1):
                cat_name = cats.get(c.category_id)
                short = (c.name or "")[:70]
                was_placeholder = is_placeholder_url(c.image_url)
                await _prog(f"[{i}/{len(need)}] Ищем: {short}")
                try:
                    url, status, host = await find_image_url(
                        c.name or "",
                        category=cat_name,
                        client=client,
                        timeout_sec=timeout,
                        google_api_key=google_api_key,
                        google_cx=google_cx,
                    )
                except Exception:
                    url, status, host = None, "error", None

                if status == "timeout":
                    timeouts += 1
                    await _prog(f"[{i}/{len(need)}] Таймаут {timeout:.0f}с: {short}")
                    await asyncio.sleep(0.15)
                    if is_placeholder_url(c.image_url):
                        c.image_url = placeholder_data_uri(cat_name)
                        placeholder_filled += 1
                elif url and status == "ok":
                    c.image_url = url
                    web_filled += 1
                    if was_placeholder:
                        placeholders_replaced += 1
                    await _prog(f"[{i}/{len(need)}] OK ← {host}: {short}")
                else:
                    if is_placeholder_url(c.image_url):
                        c.image_url = placeholder_data_uri(cat_name)
                        placeholder_filled += 1
                    await _prog(f"[{i}/{len(need)}] нет фото → SVG: {short}")
                if i % 10 == 0:
                    db.commit()
        db.commit()

    left = [
        c for c in db.query(models.Component).all()
        if is_placeholder_url(c.image_url) and not c.image_url
    ]
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
        "placeholders_replaced": placeholders_replaced,
        "timeouts": timeouts,
    }
