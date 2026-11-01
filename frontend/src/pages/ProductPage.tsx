import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ComponentDetail,
  ProductEnrichment,
  fetchComponent,
  fetchProductEnrichment,
  formatPrice,
} from '../api'
import './ProductPage.css'

function parseSpecs(raw: ComponentDetail['specs']): Record<string, string> {
  if (!raw) return {}
  if (typeof raw === 'string') {
    try {
      const o = JSON.parse(raw)
      if (o && typeof o === 'object') {
        return Object.fromEntries(
          Object.entries(o).map(([k, v]) => [k, String(v ?? '')]),
        )
      }
    } catch {
      return {}
    }
  }
  if (typeof raw === 'object') {
    return Object.fromEntries(
      Object.entries(raw).map(([k, v]) => [k, String(v ?? '')]),
    )
  }
  return {}
}

export function ProductPage() {
  const { id } = useParams()
  const componentId = Number(id)
  const [item, setItem] = useState<ComponentDetail | null>(null)
  const [enrich, setEnrich] = useState<ProductEnrichment | null>(null)
  const [loading, setLoading] = useState(true)
  const [enrichLoading, setEnrichLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!Number.isFinite(componentId) || componentId <= 0) {
      setError('Некорректный id товара')
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchComponent(componentId)
      .then((data) => {
        if (!cancelled) setItem(data)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [componentId])

  useEffect(() => {
    if (!Number.isFinite(componentId) || componentId <= 0) return
    let cancelled = false
    setEnrichLoading(true)
    fetchProductEnrichment(componentId)
      .then((data) => {
        if (!cancelled) setEnrich(data)
      })
      .catch(() => {
        if (!cancelled) setEnrich(null)
      })
      .finally(() => {
        if (!cancelled) setEnrichLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [componentId])

  const specs = useMemo(() => parseSpecs(item?.specs), [item])
  const specEntries = useMemo(
    () => Object.entries(specs).filter(([, v]) => v && v.trim()),
    [specs],
  )

  const prices = useMemo(() => {
    if (!item?.prices?.length) return []
    return [...item.prices]
      .filter((p) => p.price != null)
      .sort((a, b) => (a.price ?? 0) - (b.price ?? 0))
  }, [item])

  const minPrice = prices[0]?.price ?? null
  const description = enrich?.description || item?.description || null

  if (loading) {
    return (
      <div className="product-page">
        <div className="product-loading">Загрузка карточки…</div>
      </div>
    )
  }

  if (error || !item) {
    return (
      <div className="product-page">
        <div className="product-error">{error || 'Товар не найден'}</div>
        <Link to="/" className="btn btn-outline">
          ← В каталог
        </Link>
      </div>
    )
  }

  return (
    <div className="product-page">
      <div className="product-breadcrumb">
        <Link to="/">Каталог</Link>
        {item.category && (
          <>
            <span>/</span>
            <span>{item.category.name_ru || item.category.name}</span>
          </>
        )}
        <span>/</span>
        <span className="current">{item.name}</span>
      </div>

      <div className="product-hero">
        <div className="product-gallery">
          {item.image_url ? (
            <img src={item.image_url} alt={item.name} />
          ) : (
            <div className="product-no-image">Нет фото</div>
          )}
        </div>

        <div className="product-main">
          {item.brand && <div className="product-brand">{item.brand}</div>}
          <h1 className="product-title">{item.name}</h1>
          {item.model && <div className="product-model">Модель: {item.model}</div>}

          <div className="product-price-block">
            <div className="product-price">{formatPrice(minPrice)}</div>
            <div className="product-price-note">
              {prices.length > 1
                ? `от ${prices.length} предложений в базе`
                : prices.length === 1
                  ? 'цена из каталога'
                  : 'цена не указана'}
            </div>
          </div>

          <div className="product-actions">
            {prices[0]?.product_url && (
              <a className="btn btn-primary" href={prices[0].product_url} target="_blank" rel="noopener noreferrer">
                Открыть в магазине ↗
              </a>
            )}
            {enrich?.manufacturer_model_url && (
              <a className="btn btn-outline" href={enrich.manufacturer_model_url} target="_blank" rel="noopener noreferrer">
                Страница модели у производителя ↗
              </a>
            )}
            {enrich?.manufacturer_home && (
              <a className="btn btn-ghost" href={enrich.manufacturer_home} target="_blank" rel="noopener noreferrer">
                Сайт производителя
              </a>
            )}
          </div>

          {prices.length > 0 && (
            <div className="product-stores">
              <h3>Цены в базе</h3>
              <ul>
                {prices.map((p) => (
                  <li key={p.id}>
                    <span className="store-name">{p.store?.name || 'Магазин'}</span>
                    <span className="store-price">{formatPrice(p.price)}</span>
                    {p.product_url && (
                      <a href={p.product_url} target="_blank" rel="noopener noreferrer">ссылка</a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <section className="product-section">
        <h2>Описание</h2>
        {enrichLoading && !description ? (
          <p className="muted">Подгружаем описание из открытых источников…</p>
        ) : description ? (
          <>
            <p className="product-description">{description}</p>
            {enrich?.description_source && (
              <p className="muted small">
                Источник: {enrich.description_source}
                {enrich.description_url && (
                  <>
                    {' · '}
                    <a href={enrich.description_url} target="_blank" rel="noopener noreferrer">открыть</a>
                  </>
                )}
              </p>
            )}
          </>
        ) : (
          <p className="muted">Описание пока не найдено в открытых источниках.</p>
        )}
      </section>

      <section className="product-section">
        <h2>Характеристики</h2>
        {specEntries.length === 0 ? (
          <p className="muted">Характеристики не заполнены.</p>
        ) : (
          <table className="product-specs">
            <tbody>
              {specEntries.map(([k, v]) => (
                <tr key={k}>
                  <th>{k}</th>
                  <td>{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="product-section">
        <h2>Обзоры и упоминания</h2>
        {enrichLoading ? (
          <p className="muted">Ищем упоминания в открытой выдаче…</p>
        ) : enrich?.reviews?.length ? (
          <>
            <p className="muted small">{enrich.reviews_note}</p>
            <div className="product-reviews">
              {enrich.reviews.map((r, i) => (
                <article key={i} className="review-card">
                  <h4>{r.title}</h4>
                  <p>{r.snippet}</p>
                  {r.url && (
                    <a href={r.url} target="_blank" rel="noopener noreferrer">Источник ↗</a>
                  )}
                </article>
              ))}
            </div>
          </>
        ) : (
          <p className="muted">{enrich?.reviews_note || 'Ничего не найдено.'}</p>
        )}
      </section>
    </div>
  )
}
