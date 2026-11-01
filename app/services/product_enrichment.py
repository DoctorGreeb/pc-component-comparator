"""
Обогащение карточек товара: описание, обзоры и автоматический поиск характеристик.
"""
from __future__ import annotations

import asyncio
import json
import re
from html import unescape
from typing import Any
from urllib.parse import quote, quote_plus, unquote, urlparse

import httpx

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

MANUFACTURER_HOME = {
    "amd": "https://www.amd.com/en.html", "intel": "https://www.intel.com/",
    "nvidia": "https://www.nvidia.com/", "asus": "https://www.asus.com/",
    "asrock": "https://www.asrock.com/", "msi": "https://www.msi.com/",
    "gigabyte": "https://www.gigabyte.com/", "corsair": "https://www.corsair.com/",
    "kingston": "https://www.kingston.com/", "samsung": "https://www.samsung.com/",
    "western digital": "https://www.westerndigital.com/", "seagate": "https://www.seagate.com/",
    "crucial": "https://www.crucial.com/", "g.skill": "https://www.gskill.com/",
    "thermalright": "https://www.thermalright.com/", "deepcool": "https://www.deepcool.com/",
    "cooler master": "https://www.coolermaster.com/", "be quiet": "https://www.bequiet.com/",
    "seasonic": "https://seasonic.com/", "thermaltake": "https://www.thermaltake.com/",
    "fractal design": "https://www.fractal-design.com/", "lian li": "https://lian-li.com/",
    "nzxt": "https://nzxt.com/", "palit": "https://www.palit.com/",
    "zotac": "https://www.zotac.com/", "sapphire": "https://www.sapphiretech.com/",
    "adata": "https://www.adata.com/",
}


def _clean_query(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[「」【】\[\](){}]", " ", value or "")).strip()[:180]


def _plain_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", value or "")
    value = re.sub(r"(?s)<[^>]+", " ", value)
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _brand_key(brand: str | None, name: str) -> str:
    value = (brand or "").strip().lower()
    if value:
        return value
    lower = (name or "").lower()
    return next((key for key in sorted(MANUFACTURER_HOME, key=len, reverse=True) if key in lower), "")
