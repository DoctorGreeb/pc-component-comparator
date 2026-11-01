import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ComponentDetail, ProductEnrichment, fetchComponent, fetchProductEnrichment,
  findComponentSpecs, formatPrice,
} from '../api'
import './ProductPage.css'

function parseSpecs(raw: ComponentDetail['specs']): Record<string, string> {
  if (!raw) return {}
  if (typeof raw === 'string') {
    try {
      const value = JSON.parse(raw)
      if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, String(v ?? '')]))
    } catch { return {} }
  }
  if (typeof raw === 'object') return Object.fromEntries(Object.entries(raw).map(([k, v]) => [k, String(v ?? '')]))
  return {}
}

export function ProductPage() {
  const { id } = useParams()
  const componentId = Number(id)
  const [item, setItem] = useState<ComponentDetail | null>(null)
  const [enrich, setEnrich] = useState<ProductEnrichment | null>(null)
  const [loading, setLoading] = useState(true)
  const [enrichLoading, setEnrichLoading] = useState(true)
  const [specSearchLoading, setSpecSearchLoading] = useState(false)
  const [specSearchMessage, setSpecSearchMessage] = useState<string | null>(null)
  const [specSearchError, setSpecSearchError] = useState(false)
  const [specSearchSourceUrl, setSpecSearchSourceUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const searchedId = useRef<number | null>(null)

  useEffect(() => {
    if (!Number.isFinite(componentId) || componentId <= 0) {
      setError('Некорректный id товара'); setLoading(false); return
    }
    let cancelled = false
    setLoading(true); setItem(null); setError(null)
    setSpecSearchMessage(null); setSpecSearchSourceUrl(null); setSpecSearchError(false)
    fetchComponent(componentId)
      .then((data) => { if (!cancelled) setItem(data) })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [componentId])

  useEffect(() => {
    if (!Number.isFinite(componentId) || componentId <= 0) return
    let cancelled = false
    setEnrichLoading(true)
    fetchProductEnrichment(componentId)
      .then((data) => { if (!cancelled) setEnrich(data) })
      .catch(() => { if (!cancelled) setEnrich(null) })
      .finally(() => { if (!cancelled) setEnrichLoading(false) })
    return () => { cancelled = true }
  }, [componentId])

  const specs = useMemo(() => parseSpecs(item?.specs), [item])
  const specEntries = useMemo(() => Object.entries(specs).filter(([, value]) => value && value.trim()), [specs])

  const runSpecsSearch = async (force = false) => {
    if (specSearchLoading || (!force && searchedId.current === componentId)) return
    searchedId.current = componentId
    setSpecSearchLoading(true); setSpecSearchMessage('Автоматически ищем характеристики в интернете…')
    setSpecSearchError(false); setSpecSearchSourceUrl(null)
    try {
      const result = await findComponentSpecs(componentId)
      setSpecSearchMessage(result.message)
      setSpecSearchSourceUrl(result.source_url || null)
      if (result.status === 'ok' || result.status === 'already_filled') {
        const fresh = await fetchComponent(componentId)
        setItem(fresh)
      } else {
        setSpecSearchError(true)
      }
    } catch (e) {
      setSpecSearchError(true)
      setSpecSearchMessage(e instanceof Error ? e.message : 'Не удалось найти характеристики')
    } finally {
      setSpecSearchLoading(false)
    }
  }

  // Start the search as soon as an empty product card has loaded.
  useEffect(() => {
    if (!item || specEntries.length > 0 || loading || searchedId.current === componentId) return
    void runSpecsSearch()
  }, [item, specEntries.length, loading, componentId])

  const prices = useMemo(() => !item?.prices?.length ? [] : [...item.prices]
    .filter((price) => price.price != null && price.in_stock)
    .sort((a, b) => (a.price ?? 0) - (b.price ?? 0)), [item])
  const minPrice = prices[0]?.price ?? null
  const description = enrich?.description || item?.description || null

  if (loading) return <div className="product-page"><div className="product-loading">Загрузка карточки…</div></div>
  if (error || !item) return <div className="product-page"><div className="product-error">{error || 'Товар не найден'}</div><Link to="/" className="btn btn-outline">← В каталог</Link></div>

  return (
    <div className="product-page">
      <div className="product-breadcrumb">
        <Link to="/">Каталог</Link>
        {item.category && <><span>/</span><span>{item.category.name_ru || item.category.name}</span></>}
        <span>/</span><span className="current">{item.name}</span>
      </div>
      <div className="product-hero">
        <div className="product-gallery">
          {item.image_url ? <img src={item.image_url} alt={item.name} /> : <div className="product-no-image">Нет фото</div>}
        </div>
        <div className="product-main">
          {item.brand && <div className="product-brand">{item.brand}</div>}
          <h1 className="product-title">{item.name}</h1>
          {item.model && <div className="product-model">Модель: {item.model}</div>}
          <div className="product-price-block">
            <div className="product-price">{formatPrice(minPrice)}</div>
            <div className="product-price-note">{prices.length > 1 ? `от ${prices.length} предложений в базе` : prices.length === 1 ? 'цена из каталога' : 'цена не указана'}</div>
          </div>
          <div className="product-actions">
            {prices[0]?.product_url && <a className="btn btn-primary" href={prices[0].product_url} target="_blank" rel="noopener noreferrer">Открыть в магазине ↗</a>}
            {enrich?.manufacturer_model_url && <a className="btn btn-outline" href={enrich.manufacturer_model_url} target="_blank" rel="noopener noreferrer">Страница модели у производителя ↗</a>}
            {enrich?.manufacturer_home && <a className="btn btn-ghost" href={enrich.manufacturer_home} target="_blank" rel="noopener noreferrer">Сайт производителя</a>}
          </div>
          {prices.length > 0 && <div className="product-stores"><h3>Цены в базе</h3><ul>{prices.map((price) => <li key={price.id}>
            <span className="store-name">{price.store?.name || 'Магазин'}</span><span className="store-price">{formatPrice(price.price)}</span>
            {price.product_url && <a href={price.product_url} target="_blank" rel="noopener noreferrer">ссылка</a>}
          </li>)}</ul></div>}
        </div>
      </div>
      <section className="product-section">
        <h2>Описание</h2>
        {enrichLoading && !description ? <p className="muted">Подгружаем описание из открытых источников…</p> : description ? <>
          <p className="product-description">{description}</p>
          {enrich?.description_source && <p className="muted small">Источник: {enrich.description_source}{enrich.description_url && <> · <a href={enrich.description_url} target="_blank" rel="noopener noreferrer">открыть</a></>}</p>}
        </> : <p className="muted">Описание пока не найдено в открытых источниках.</p>}
      </section>
      <section className="product-section">
        <h2>Характеристики</h2>
        {specEntries.length === 0 ? <div className="product-specs-empty">
          <p className="muted">{specSearchLoading ? 'Ищем характеристики: сначала по сниппетам, затем на страницах магазинов…' : specSearchMessage || 'Характеристики пока не найдены автоматически.'}</p>
          {specSearchMessage && <div className={specSearchError ? 'product-specs-error' : 'muted'} role="status">
            {specSearchSourceUrl && <a href={specSearchSourceUrl} target="_blank" rel="noopener noreferrer">Открыть источник ↗</a>}
          </div>}
          {!specSearchLoading && specSearchError && <button type="button" className="btn btn-outline" onClick={() => void runSpecsSearch(true)}>Повторить поиск</button>}
        </div> : <>
          <table className="product-specs"><tbody>{specEntries.map(([key, value]) => <tr key={key}><th>{key}</th><td>{value}</td></tr>)}</tbody></table>
          {specSearchSourceUrl && <p className="muted small">Источник: <a href={specSearchSourceUrl} target="_blank" rel="noopener noreferrer">открыть страницу ↗</a></p>}
        </>}
      </section>
      <section className="product-section">
        <h2>Обзоры и упоминания</h2>
        {enrichLoading ? <p className="muted">Ищем упоминания в открытой выдаче…</p> : enrich?.reviews?.length ? <>
          <p className="muted small">{enrich.reviews_note}</p>
          <div className="product-reviews">{enrich.reviews.map((review, index) => <article key={index} className="review-card">
            <h4>{review.title}</h4><p>{review.snippet}</p>
            {review.url && <a href={review.url} target="_blank" rel="noopener noreferrer">Источник ↗</a>}
          </article>)}</div>
        </> : <p className="muted">{enrich?.reviews_note || 'Ничего не найдено.'}</p>}
      </section>
    </div>
  )
}
