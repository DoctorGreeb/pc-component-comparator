import { useEffect, useState, useCallback, useMemo } from 'react'
import {
  fetchCategories,
  fetchComponents,
  fetchFacets,
  Category,
  ComponentListItem,
  FacetsResponse,
  SortOption,
  formatPrice,
} from '../api'
import { SelectedItem } from '../App'
import './CatalogPage.css'

interface Props {
  selected: SelectedItem[]
  onToggle: (item: SelectedItem) => void
}

const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: 'price_asc', label: 'Цена ↑' },
  { value: 'price_desc', label: 'Цена ↓' },
  { value: 'name_asc', label: 'Название А–Я' },
  { value: 'name_desc', label: 'Название Я–А' },
]

export function CatalogPage({ selected, onToggle }: Props) {
  const [categories, setCategories] = useState<Category[]>([])
  const [activeCategory, setActiveCategory] = useState<string | null>(null)
  const [components, setComponents] = useState<ComponentListItem[]>([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<SortOption>('price_asc')
  const [facets, setFacets] = useState<FacetsResponse | null>(null)
  const [selectedBrands, setSelectedBrands] = useState<string[]>([])
  const [selectedSpecs, setSelectedSpecs] = useState<Record<string, string[]>>({})
  const [priceMin, setPriceMin] = useState('')
  const [priceMax, setPriceMax] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const limit = 48

  useEffect(() => {
    fetchCategories()
      .then(setCategories)
      .catch(() => setError('Не удалось загрузить категории. Обновите базу.'))
  }, [])

  useEffect(() => {
    setSelectedBrands([])
    setSelectedSpecs({})
    setPriceMin('')
    setPriceMax('')
    setPage(0)
    fetchFacets(activeCategory || undefined)
      .then(setFacets)
      .catch(() => setFacets(null))
  }, [activeCategory])

  const specQuery = useMemo(() => {
    const list: string[] = []
    Object.entries(selectedSpecs).forEach(([key, vals]) => {
      vals.forEach((v) => list.push(`${key}:${v}`))
    })
    return list
  }, [selectedSpecs])

  const loadComponents = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchComponents({
        category: activeCategory || undefined,
        q: search.trim() || undefined,
        sort,
        brand: selectedBrands.length ? selectedBrands.join(',') : undefined,
        price_min: priceMin ? Number(priceMin) : undefined,
        price_max: priceMax ? Number(priceMax) : undefined,
        spec: specQuery.length ? specQuery : undefined,
        skip: page * limit,
        limit,
      })
      setComponents(data.items)
      setTotal(data.total)
    } catch {
      setError('Ошибка загрузки компонентов')
      setComponents([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [activeCategory, search, sort, selectedBrands, priceMin, priceMax, specQuery, page])

  useEffect(() => {
    const t = setTimeout(loadComponents, 200)
    return () => clearTimeout(t)
  }, [loadComponents])

  const isSelected = (id: number) => selected.some((s) => s.id === id)
  const currentCategoryId = selected[0]?.categoryId

  const handleToggle = (c: ComponentListItem) => {
    onToggle({
      id: c.id,
      name: c.name,
      categoryId: c.category_id,
      categoryName: c.category_name || '',
    })
  }

  const toggleBrand = (b: string) => {
    setPage(0)
    setSelectedBrands((prev) =>
      prev.includes(b) ? prev.filter((x) => x !== b) : [...prev, b],
    )
  }

  const toggleSpec = (key: string, value: string) => {
    setPage(0)
    setSelectedSpecs((prev) => {
      const cur = prev[key] || []
      const next = cur.includes(value)
        ? cur.filter((x) => x !== value)
        : [...cur, value]
      return { ...prev, [key]: next }
    })
  }

  const clearFilters = () => {
    setSelectedBrands([])
    setSelectedSpecs({})
    setPriceMin('')
    setPriceMax('')
    setPage(0)
  }

  const totalPages = Math.max(1, Math.ceil(total / limit))
  const hasFilters =
    selectedBrands.length > 0 ||
    Object.values(selectedSpecs).some((v) => v.length > 0) ||
    priceMin !== '' ||
    priceMax !== ''

  return (
    <div className="catalog">
      <aside className="sidebar">
        <h2 className="sidebar-title">Категории</h2>
        <ul className="category-list">
          <li>
            <button
              className={`category-btn ${activeCategory === null ? 'active' : ''}`}
              onClick={() => setActiveCategory(null)}
            >
              Все
            </button>
          </li>
          {categories.map((cat) => (
            <li key={cat.id}>
              <button
                className={`category-btn ${activeCategory === cat.name ? 'active' : ''}`}
                onClick={() => setActiveCategory(cat.name)}
              >
                {cat.name_ru}
              </button>
            </li>
          ))}
        </ul>

        {facets && (
          <div className="filters">
            <div className="filters-head">
              <h2 className="sidebar-title">Фильтры</h2>
              {hasFilters && (
                <button type="button" className="clear-filters" onClick={clearFilters}>
                  Сбросить
                </button>
              )}
            </div>

            <div className="filter-group">
              <div className="filter-label">Цена, ₽</div>
              <div className="price-range">
                <input
                  type="number"
                  placeholder={facets.price_min != null ? String(Math.floor(facets.price_min)) : 'от'}
                  value={priceMin}
                  onChange={(e) => {
                    setPriceMin(e.target.value)
                    setPage(0)
                  }}
                />
                <span>—</span>
                <input
                  type="number"
                  placeholder={facets.price_max != null ? String(Math.ceil(facets.price_max)) : 'до'}
                  value={priceMax}
                  onChange={(e) => {
                    setPriceMax(e.target.value)
                    setPage(0)
                  }}
                />
              </div>
            </div>

            {facets.brands.length > 0 && (
              <div className="filter-group">
                <div className="filter-label">Бренд</div>
                <div className="filter-values">
                  {facets.brands.slice(0, 12).map((b) => (
                    <label key={b.value} className="filter-check">
                      <input
                        type="checkbox"
                        checked={selectedBrands.includes(b.value)}
                        onChange={() => toggleBrand(b.value)}
                      />
                      <span>
                        {b.value} <em>({b.count})</em>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            )}

            {facets.specs.map((f) => (
              <div key={f.key} className="filter-group">
                <div className="filter-label">{f.key}</div>
                <div className="filter-values">
                  {f.values.slice(0, 8).map((v) => (
                    <label key={v.value} className="filter-check">
                      <input
                        type="checkbox"
                        checked={(selectedSpecs[f.key] || []).includes(v.value)}
                        onChange={() => toggleSpec(f.key, v.value)}
                      />
                      <span>
                        {v.value} <em>({v.count})</em>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </aside>

      <section className="content">
        <div className="toolbar">
          <input
            type="search"
            className="search-input"
            placeholder={
              activeCategory
                ? 'Поиск в категории…'
                : 'Поиск по всем комплектующим…'
            }
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(0)
            }}
          />
          <select
            className="sort-select"
            value={sort}
            onChange={(e) => {
              setSort(e.target.value as SortOption)
              setPage(0)
            }}
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        <div className="results-meta">
          Найдено: <strong>{total}</strong>
          {loading && <span className="loading-inline"> · загрузка…</span>}
        </div>

        {error && <div className="message error">{error}</div>}

        {!loading && components.length === 0 && !error && (
          <div className="message empty">
            Нет товаров. Введите API-ключ ReefAPI, нажмите «Применить» и «Обновить базу».
          </div>
        )}

        <div className="grid">
          {components.map((c) => {
            const selectedHere = isSelected(c.id)
            const disabledByCategory =
              currentCategoryId !== undefined &&
              currentCategoryId !== c.category_id &&
              !selectedHere

            return (
              <article
                key={c.id}
                className={`card ${selectedHere ? 'selected' : ''} ${disabledByCategory ? 'disabled' : ''}`}
              >
                <div className="card-image">
                  {c.image_url ? (
                    <img src={c.image_url} alt={c.name} loading="lazy" />
                  ) : (
                    <div className="placeholder">Нет фото</div>
                  )}
                  <label className="checkbox-wrap">
                    <input
                      type="checkbox"
                      checked={selectedHere}
                      disabled={
                        disabledByCategory || (selected.length >= 4 && !selectedHere)
                      }
                      onChange={() => handleToggle(c)}
                    />
                    <span className="checkbox-label">В сравнение</span>
                  </label>
                </div>
                <div className="card-body">
                  {c.brand && <div className="brand">{c.brand}</div>}
                  <h3 className="name" title={c.name}>
                    {c.name}
                  </h3>
                  {c.description && (
                    <p className="short-specs" title={c.description}>
                      {c.description}
                    </p>
                  )}
                  <div className="price-row">
                    <span className="price">{formatPrice(c.min_price)}</span>
                    {c.old_price != null && c.min_price != null && c.old_price > c.min_price && (
                      <span className="old-price">{formatPrice(c.old_price)}</span>
                    )}
                  </div>
                  {c.product_url && (
                    <a
                      className="store-link"
                      href={c.product_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                    >
                      DNS ↗
                    </a>
                  )}
                </div>
              </article>
            )
          })}
        </div>

        {totalPages > 1 && (
          <div className="pagination">
            <button
              className="btn btn-outline"
              disabled={page <= 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              Назад
            </button>
            <span>
              {page + 1} / {totalPages}
            </span>
            <button
              className="btn btn-outline"
              disabled={page + 1 >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              Вперёд
            </button>
          </div>
        )}
      </section>
    </div>
  )
}
