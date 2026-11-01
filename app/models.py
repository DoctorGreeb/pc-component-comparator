from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)  # cpu, gpu, motherboard, ram, ssd, psu, case, cooler
    name_ru: Mapped[str] = mapped_column(String(100))

    components: Mapped[list["Component"]] = relationship(back_populates="category")


class Component(Base):
    __tablename__ = "components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(String(255), index=True)
    brand: Mapped[str | None] = mapped_column(String(100), index=True)
    model: Mapped[str | None] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(500))
    specs: Mapped[str | None] = mapped_column(Text)  # JSON string with characteristics
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category: Mapped["Category"] = relationship(back_populates="components")
    prices: Mapped[list["Price"]] = relationship(back_populates="component", cascade="all, delete-orphan")


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)  # DNS, Citilink, Regard
    url: Mapped[str | None] = mapped_column(String(255))

    prices: Mapped[list["Price"]] = relationship(back_populates="store")


class Price(Base):
    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    price: Mapped[float | None] = mapped_column(Float)
    old_price: Mapped[float | None] = mapped_column(Float)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    product_url: Mapped[str | None] = mapped_column(String(500))
    external_id: Mapped[str | None] = mapped_column(String(100))  # ID from store
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    component: Mapped["Component"] = relationship(back_populates="prices")
    store: Mapped["Store"] = relationship(back_populates="prices")
