import { useEffect, useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { fetchCompare, ComponentDetail } from '../api'
import './ComparePage.css'

export function ComparePage() {
  const [params] = useSearchParams()
  const idsParam = params.get('ids') || ''
  const [data, setData] = useState<{
    category: string | null
    category_ru: string | null
    components: ComponentDetail[]
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

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

  // Collect all unique spec keys
  const allKeys = new Set<string>()
  components.forEach((c) => {
    if (c.specs && typeof c.specs === 'object') {
      Object.keys(c.specs).forEach((k) => allKeys.add(k))
    }
  })
  const specKeys = Array.from(allKeys).sort()

  return (
    <div className="compare">
      <div className="compare-header">
        <Link to="/" className="back-link">
          ← Каталог
        </Link>
        <h1>
          Сравнение: {data.category_ru || data.category || 'компоненты'}
        </h1>
      </div>

      <div className="table-wrap">
        <table className="compare-table">
          <thead>
            <tr>
              <th className="label-col">Параметр</th>
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
            <tr>
              <td className="label-col">Цена (мин.)</td>
              {components.map((c) => {
                const prices = c.prices
                  .map((p) => p.price)
                  .filter((p): p is number => p != null)
                const min = prices.length ? Math.min(...prices) : null
                return (
                  <td key={c.id}>
                    {min != null ? `${min.toLocaleString('ru-RU')} ₽` : '—'}
                  </td>
                )
              })}
            </tr>
            <tr>
              <td className="label-col">Наличие</td>
              {components.map((c) => (
                <td key={c.id}>
                  {c.prices.some((p) => p.in_stock) ? 'В наличии' : 'Нет'}
                </td>
              ))}
            </tr>
            {specKeys.map((key) => (
              <tr key={key}>
                <td className="label-col">{key}</td>
                {components.map((c) => {
                  const specs = c.specs && typeof c.specs === 'object' ? c.specs : {}
                  const val = (specs as Record<string, unknown>)[key]
                  return (
                    <td key={c.id}>
                      {val != null && val !== '' ? String(val) : '—'}
                    </td>
                  )
                })}
              </tr>
            ))}
            {specKeys.length === 0 && (
              <tr>
                <td className="label-col" colSpan={components.length + 1}>
                  Характеристики пока не загружены (база пуста)
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
