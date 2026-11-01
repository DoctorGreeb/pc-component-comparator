from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Any


class CategoryBase(BaseModel):
    name: str
    name_ru: str


class Category(CategoryBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class StoreBase(BaseModel):
    name: str
    url: Optional[str] = None


class Store(StoreBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class PriceBase(BaseModel):
    price: Optional[float] = None
    old_price: Optional[float] = None
    in_stock: bool = False
    product_url: Optional[str] = None
    external_id: Optional[str] = None


class Price(PriceBase):
    id: int
    store_id: int
    updated_at: datetime
    store: Optional[Store] = None
    model_config = ConfigDict(from_attributes=True)


class ComponentBase(BaseModel):
    name: str
    brand: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    specs: Optional[dict[str, Any] | str] = None


class Component(ComponentBase):
    id: int
    category_id: int
    created_at: datetime
    updated_at: datetime
    category: Optional[Category] = None
    prices: list[Price] = []
    model_config = ConfigDict(from_attributes=True)


class ComponentListItem(BaseModel):
    id: int
    name: str
    brand: Optional[str] = None
    model: Optional[str] = None
    image_url: Optional[str] = None
    category_id: int
    category_name: Optional[str] = None
    description: Optional[str] = None
    min_price: Optional[float] = None
    old_price: Optional[float] = None
    product_url: Optional[str] = None
    specs: Optional[dict[str, Any]] = None
    model_config = ConfigDict(from_attributes=True)


class ComponentsPage(BaseModel):
    items: list[ComponentListItem]
    total: int
    skip: int
    limit: int


class FacetValue(BaseModel):
    value: str
    count: int


class Facet(BaseModel):
    key: str
    values: list[FacetValue]


class FacetsResponse(BaseModel):
    brands: list[FacetValue]
    specs: list[Facet]
    price_min: Optional[float] = None
    price_max: Optional[float] = None


class UpdateDatabaseRequest(BaseModel):
    api_key: Optional[str] = Field(None, description="ReefAPI key (ak_live_...)")


class UpdateDatabaseResponse(BaseModel):
    status: str
    message: str
    note: Optional[str] = None
    components_added: int = 0
    categories_ready: int = 0
