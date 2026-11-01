import { useEffect, useState, useCallback } from 'react'
import { fetchCategories, fetchComponents, Category, ComponentListItem } from '../api'
import { SelectedItem } from '../App'
import './CatalogPage.css'

interface Props {
  selected: SelectedItem[]
  onToggle: (item: SelectedItem) => void
}

export function CatalogPage({ selected, onToggle }: Props) {
  const [categories, setCategories] = useState<Category[]>([])
  const [activeCategory, setActiveCategory] = useState<string | null>(null)
  const [components, setComponents] = useState<ComponentListItem[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchCategories()
      .then(setCategories)
      .catch(() => setError('Не удалось загрузить категории. Нажмите «Обновить базу».'))
  }, [])

  const loadComponents = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchComponents({
        category: activeCategory || undefined,
        q: search.trim() || undefined,
        limit: 60,
      })
      setComponents(data)
    } catch {
      setError('Ошибка загрузки компонентов')
      setComponents([])
    } finally {
      setLoading(false)
    }
  }, [activeCategory, search])

  useEffect(() => {
    const t = setTimeout(loadComponents, 250)
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
      </aside>

      <section className="content">
        <div className="toolbar">
          <input
            type="search"
            className="search-input"
            placeholder={
              activeCategory
                ? `Поиск в категории…`
                : `Поиск по всем комплектующим…`
            }
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {error && <div className="message error">{error}</div>}
        {loading && <div className="message">Загрузка…</div>}

        {!loading && components.length === 0 && !error && (
          <div className="message empty">
            Нет компонентов. Нажмите «Обновить базу» в шапке, затем подключите API для загрузки товаров.
          </div>
        )}

        <div className="grid">
          {components.map((c) => {
            const selectedHere = isSelected(c.id)
            const disabledByCategory =
              currentCategoryId !== undefined && currentCategoryId !== c.category_id && !selectedHere

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
                      disabled={disabledByCategory || (selected.length >= 4 && !selectedHere)}
                      onChange={() => handleToggle(c)}
                    />
                    <span className="checkbox-label">В сравнение</span>
                  </label>
                </div>
                <div className="card-body">
                  {c.brand && <div className="brand">{c.brand}</div>}
                  <h3 className="name">{c.name}</h3>
                  {c.min_price != null && (
                    <div className="price">
                      {c.min_price.toLocaleString('ru-RU')} ₽
                      {c.in_stock ? (
                        <span className="stock in">В наличии</span>
                      ) : (
                        <span className="stock out">Нет в наличии</span>
                      )}
                    </div>
                  )}
                </div>
              </article>
            )
          })}
        </div>
      </section>
    </div>
  )
}
