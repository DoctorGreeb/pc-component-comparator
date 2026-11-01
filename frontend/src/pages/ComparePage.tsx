import { useEffect, useState, useMemo } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { fetchCompare, ComponentDetail, formatPrice } from '../api'
import './ComparePage.css'

function getMinPrice(c: ComponentDetail): number | null {
  const prices = c.prices.map((p) => p.price).filter((p): p is number => p != null)
  return prices.length ? Math.min(...prices) : null
}

function getOldPrice(c: ComponentDetail): number | null {
  const withPrice = c.prices.filter((p) => p.price != null)
  if (!withPrice.length) return null
  const best = withPrice.reduce((a, b) => ((a.price ?? 0) <= (b.price ?? 0) ? a : b))
  return best.old_price
}

function getProductUrl(c: ComponentDetail): string | null {
  const withUrl = c.prices.find((p) => p.product_url)
  return withUrl?.product_url || null
}

function specVal(c: ComponentDetail, key: string): string {
  const specs =
    c.specs && typeof c.specs === 'object' ? (c.specs as Record<string, unknown>) : {}
  const v = specs[key]
  return v != null && v !== '' ? String(v) : '—'
}

export function ComparePage() {
  const [params] = useSearchParams()
  const idsParam = params.get('ids') || ''
  const [data, setData] = useState<{
    category: string | null
    category_ru: string | null
    spec_keys: string[]
    components: ComponentDetail[]
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [onlyDiff, setOnlyDiff] = useState(false)

  useEffect(() => {
    const ids = idsParam
      .split(',')
      .map((x) => parseInt(x.trim(), 10))
      .filter((n) => !isNaN(n))

    if (ids.length < 2) {
      setError('Нужно выбрать минимум 2 компонента')
      setLoading(false)
      return
    }

    setLoading(true)
    fetchCompare(ids)
      .then(setData)
      .catch((e) => setError(e.message || 'Ошибка сравнения'))
      .finally(() => setLoading(false))
  }, [idsParam])

  const diffKeys = useMemo(() => {
    if (!data) return new Set<string>()
    const set = new Set<string>()
    for (const key of data.spec_keys) {
      const values = data.components.map((c) => specVal(c, key))
      if (new Set(values).size > 1) set.add(key)
    }
    return set
  }, [data])

  if (loading) {
    return <div className="compare-message">Загрузка сравнения…</div>
  }

  if (error || !data) {
    return (
      <div className="compare-message error">
        <p>{error || 'Нет данных'}</p>
        <Link to="/" className="back-link">
          ← Вернуться в каталог
        </Link>
      </div>
    )
  }

  const components = data.components
  const keys = onlyDiff
    ? data.spec_keys.filter((k) => diffKeys.has(k))
    : data.spec_keys

  const prices = components.map(getMinPrice)
  const priceDiff = new Set(prices.map((p) => p ?? -1)).size > 1
  const hasDescription = components.some((c) => c.description)

  return (
    <div className="compare">
      <div className="compare-header">
        <div>
          <Link to="/" className="back-link">
            ← Каталог
          </Link>
          <h1>Сравнение: {data.category_ru || data.category || 'компоненты'}</h1>
          <p className="compare-sub">
            {components.length} позиций · характеристики из DNS
          </p>
        </div>
        <label className="only-diff">
          <input
            type="checkbox"
            checked={onlyDiff}
            onChange={(e) => setOnlyDiff(e.target.checked)}
          />
          Только отличия
        </label>
      </div>

      <div className="table-wrap">
        <table className="compare-table">
          <thead>
            <tr>
              <th className="label-col sticky-col">Параметр</th>
              {components.map((c) => (
                <th key={c.id}>
                  <div className="comp-head">
                    {c.image_url && (
                      <img src={c.image_url} alt="" className="comp-thumb" />
                    )}
                    <div className="comp-name">{c.name}</div>
                    {c.brand && <div className="comp-brand">{c.brand}</div>}
                    {getProductUrl(c) && (
                      <a
                        className="comp-link"
                        href={getProductUrl(c)!}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Открыть в DNS ↗
                      </a>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className={priceDiff ? 'row-diff' : ''}>
              <td className="label-col sticky-col">Цена</td>
              {components.map((c) => {
                const p = getMinPrice(c)
                const old = getOldPrice(c)
                return (
                  <td key={c.id} className="price-cell">
                    <span className="cmp-price">{formatPrice(p)}</span>
                    {old != null && p != null && old > p && (
                      <span className="cmp-old">{formatPrice(old)}</span>
                    )}
                  </td>
                )
              })}
            </tr>

            {hasDescription && (
              <tr>
                <td className="label-col sticky-col">Кратко</td>
                {components.map((c) => (
                  <td key={c.id} className="desc-cell">
                    {c.description || '—'}
                  </td>
                ))}
              </tr>
            )}

            {keys.map((key) => {
              const isDiff = diffKeys.has(key)
              return (
                <tr key={key} className={isDiff ? 'row-diff' : ''}>
                  <td className="label-col sticky-col">{key}</td>
                  {components.map((c) => (
                    <td key={c.id}>{specVal(c, key)}</td>
                  ))}
                </tr>
              )
            })}

            {keys.length === 0 && (
              <tr>
                <td className="label-col" colSpan={components.length + 1}>
                  {onlyDiff
                    ? 'Все характеристики совпадают'
                    : 'Характеристики пока не загружены — обновите базу'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
