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
  return c.prices.find((p) => p.product_url)?.product_url || null
}

function specVal(c: ComponentDetail, key: string): string {
  const specs =
    c.specs && typeof c.specs === 'object' ? (c.specs as Record<string, unknown>) : {}
  const v = specs[key]
  return v != null && v !== '' ? String(v) : '—'
}

/** Извлечь первое число из строки характеристики */
function extractNumber(s: string): number | null {
  const m = s.replace(/\s/g, '').match(/(\d+[.,]?\d*)/)
  if (!m) return null
  return parseFloat(m[1].replace(',', '.'))
}

/** Ключи, где больше = лучше */
const HIGHER_BETTER = [
  'объем',
  'ядер',
  'потоков',
  'частот',
  'кэш',
  'памят',
  'скорост',
  'мощност',
  'tdp',
  'ресурс',
  'tbw',
  'разрядн',
]

/** Ключи, где меньше = лучше (кроме цены) */
const LOWER_BETTER = ['тепловыдел', 'тайминг', 'задерж', 'latency', 'толщин', 'шум']

function isHigherBetter(key: string): boolean | null {
  const k = key.toLowerCase()
  if (LOWER_BETTER.some((x) => k.includes(x))) return false
  if (HIGHER_BETTER.some((x) => k.includes(x))) return true
  return null
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
  const [onlyDiff, setOnlyDiff] = useState(true)
  const [copied, setCopied] = useState(false)

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

  const analysis = useMemo(() => {
    if (!data) return null
    const comps = data.components
    const prices = comps.map(getMinPrice)
    const valid = prices.filter((p): p is number => p != null)
    const minPrice = valid.length ? Math.min(...valid) : null
    const maxPrice = valid.length ? Math.max(...valid) : null
    const cheapestIds = new Set(
      comps.filter((c) => getMinPrice(c) === minPrice && minPrice != null).map((c) => c.id),
    )

    // лучшие по числовым характеристикам
    const wins: Record<number, string[]> = {}
    comps.forEach((c) => {
      wins[c.id] = []
    })

    for (const key of data.spec_keys) {
      const direction = isHigherBetter(key)
      if (direction === null) continue
      const nums = comps.map((c) => ({
        id: c.id,
        n: extractNumber(specVal(c, key)),
      }))
      const present = nums.filter((x) => x.n != null) as { id: number; n: number }[]
      if (present.length < 2) continue
      const best = direction
        ? Math.max(...present.map((x) => x.n))
        : Math.min(...present.map((x) => x.n))
      present
        .filter((x) => x.n === best)
        .forEach((x) => {
          if (!wins[x.id].includes(key)) wins[x.id].push(key)
        })
    }

    const save =
      minPrice != null && maxPrice != null && maxPrice > minPrice
        ? maxPrice - minPrice
        : null

    return { minPrice, maxPrice, cheapestIds, wins, save }
  }, [data])

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* ignore */
    }
  }

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
  const colCount = components.length
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
            {components.length} позиций · данные DNS
            {analysis?.save != null && (
              <>
                {' · '}
                <span className="save-hint">
                  разница цен до {formatPrice(analysis.save)}
                </span>
              </>
            )}
          </p>
        </div>
        <div className="compare-actions">
          <label className="only-diff">
            <input
              type="checkbox"
              checked={onlyDiff}
              onChange={(e) => setOnlyDiff(e.target.checked)}
            />
            Только отличия
          </label>
          <button type="button" className="btn-share" onClick={copyLink}>
            {copied ? 'Ссылка скопирована' : 'Поделиться'}
          </button>
        </div>
      </div>

      {/* Карточки-итог: чем зацепить */}
      <div className="verdict-grid" style={{ gridTemplateColumns: `repeat(${colCount}, 1fr)` }}>
        {components.map((c) => {
          const price = getMinPrice(c)
          const isCheapest = analysis?.cheapestIds.has(c.id)
          const winCount = analysis?.wins[c.id]?.length || 0
          return (
            <div key={c.id} className={`verdict-card ${isCheapest ? 'is-best-price' : ''}`}>
              {c.image_url && <img src={c.image_url} alt="" className="verdict-img" />}
              <div className="verdict-name">{c.name}</div>
              <div className="verdict-price">{formatPrice(price)}</div>
              <div className="verdict-badges">
                {isCheapest && <span className="badge badge-price">Лучшая цена</span>}
                {winCount > 0 && (
                  <span className="badge badge-specs">Лидер по {winCount} парам.</span>
                )}
              </div>
              {getProductUrl(c) && (
                <a
                  className="verdict-link"
                  href={getProductUrl(c)!}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Купить на DNS ↗
                </a>
              )}
            </div>
          )
        })}
      </div>

      <div className="table-wrap">
        <table className="compare-table">
          <colgroup>
            <col className="col-label" />
            {components.map((c) => (
              <col key={c.id} className="col-item" />
            ))}
          </colgroup>
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
                const isCheapest = analysis?.cheapestIds.has(c.id)
                const delta =
                  analysis?.minPrice != null && p != null && p > analysis.minPrice
                    ? p - analysis.minPrice
                    : null
                return (
                  <td key={c.id}>
                    <div className="price-cell-inner">
                      <span className={`cmp-price ${isCheapest ? 'best' : ''}`}>
                        {formatPrice(p)}
                      </span>
                      {old != null && p != null && old > p && (
                        <span className="cmp-old">{formatPrice(old)}</span>
                      )}
                      {isCheapest && <span className="mini-badge">выгоднее</span>}
                      {delta != null && (
                        <span className="price-delta">+{formatPrice(delta)}</span>
                      )}
                    </div>
                  </td>
                )
              })}
            </tr>

            {hasDescription && (
              <tr>
                <td className="label-col sticky-col">Кратко</td>
                {components.map((c) => (
                  <td key={c.id}>
                    <div className="desc-cell">{c.description || '—'}</div>
                  </td>
                ))}
              </tr>
            )}

            {keys.map((key) => {
              const isDiff = diffKeys.has(key)
              const direction = isHigherBetter(key)
              const nums = components.map((c) => extractNumber(specVal(c, key)))
              let bestNum: number | null = null
              if (direction !== null) {
                const present = nums.filter((n): n is number => n != null)
                if (present.length >= 2) {
                  bestNum = direction ? Math.max(...present) : Math.min(...present)
                }
              }
              return (
                <tr key={key} className={isDiff ? 'row-diff' : ''}>
                  <td className="label-col sticky-col">{key}</td>
                  {components.map((c, idx) => {
                    const val = specVal(c, key)
                    const n = nums[idx]
                    const isBest = bestNum != null && n === bestNum
                    return (
                      <td key={c.id}>
                        <div className={`cell-val ${isBest ? 'is-best' : ''}`}>
                          {val}
                          {isBest && <span className="best-dot" title="Лучше в сравнении" />}
                        </div>
                      </td>
                    )
                  })}
                </tr>
              )
            })}

            {keys.length === 0 && (
              <tr>
                <td className="label-col" colSpan={components.length + 1}>
                  {onlyDiff
                    ? 'Все характеристики совпадают — снимите «Только отличия»'
                    : 'Характеристики не загружены — обновите базу'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
