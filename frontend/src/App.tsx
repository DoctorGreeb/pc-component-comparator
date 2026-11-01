import { useState, useCallback, useEffect } from 'react'
import { Routes, Route, Link, useNavigate } from 'react-router-dom'
import { CatalogPage } from './pages/CatalogPage'
import { ComparePage } from './pages/ComparePage'
import { updateDatabase } from './api'
import './App.css'

const STORAGE_KEY = 'reefapi_key'
const REEF_SIGNUP_URL = 'https://reefapi.com/signup'

export interface SelectedItem {
  id: number
  name: string
  categoryId: number
  categoryName: string
}

function App() {
  const [selected, setSelected] = useState<SelectedItem[]>([])
  const [updating, setUpdating] = useState(false)
  const [updateMsg, setUpdateMsg] = useState<string | null>(null)
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [apiKeyApplied, setApiKeyApplied] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      setApiKeyInput(saved)
      setApiKeyApplied(true)
    }
  }, [])

  const toggleSelect = useCallback((item: SelectedItem) => {
    setSelected((prev) => {
      const exists = prev.find((s) => s.id === item.id)
      if (exists) {
        return prev.filter((s) => s.id !== item.id)
      }
      if (prev.length > 0 && prev[0].categoryId !== item.categoryId) {
        return [item]
      }
      if (prev.length >= 4) {
        return prev
      }
      return [...prev, item]
    })
  }, [])

  const clearSelection = () => setSelected([])

  const handleApplyKey = () => {
    const key = apiKeyInput.trim()
    if (!key) {
      localStorage.removeItem(STORAGE_KEY)
      setApiKeyApplied(false)
      setUpdateMsg('Ключ очищен')
      return
    }
    localStorage.setItem(STORAGE_KEY, key)
    setApiKeyApplied(true)
    setUpdateMsg('Ключ ReefAPI сохранён. Можно обновить базу.')
  }

  const handleUpdateDb = async () => {
    const key = apiKeyInput.trim() || localStorage.getItem(STORAGE_KEY) || undefined
    if (!key) {
      setUpdateMsg('Сначала введите и примените API-ключ ReefAPI.')
      return
    }
    setUpdating(true)
    setUpdateMsg(null)
    try {
      const res = await updateDatabase(key)
      setUpdateMsg(res.message + (res.note ? ` (${res.note})` : ''))
    } catch (e) {
      setUpdateMsg(e instanceof Error ? e.message : 'Ошибка обновления базы')
    } finally {
      setUpdating(false)
    }
  }

  const goToCompare = () => {
    if (selected.length >= 2) {
      navigate(`/compare?ids=${selected.map((s) => s.id).join(',')}`)
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <Link to="/" className="logo">
            PC Comparator
          </Link>
          <nav className="nav">
            <Link to="/">Каталог</Link>
          </nav>

          <div className="api-key-block">
            <div className="api-key-row">
              <label className="api-key-label" htmlFor="api-key-input">
                ReefAPI ключ
                <span className="help-tip" tabIndex={0}>
                  ?
                  <span className="help-tip-content">
                    Для загрузки реальных товаров из DNS нужен бесплатный
                    API-ключ ReefAPI. Зарегистрируйтесь на сайте, скопируйте
                    ключ (ak_live_...) и вставьте сюда, затем нажмите
                    «Применить» и «Обновить базу».
                  </span>
                </span>
              </label>
              <input
                id="api-key-input"
                type="password"
                className="api-key-input"
                placeholder="ak_live_..."
                value={apiKeyInput}
                onChange={(e) => {
                  setApiKeyInput(e.target.value)
                  setApiKeyApplied(false)
                }}
                autoComplete="off"
              />
              <button type="button" className="btn btn-outline btn-sm" onClick={handleApplyKey}>
                Применить
              </button>
              <a
                className="btn btn-ghost btn-sm link-external"
                href={REEF_SIGNUP_URL}
                target="_blank"
                rel="noopener noreferrer"
              >
                Получить ключ
              </a>
            </div>
            {apiKeyApplied && (
              <span className="api-key-status">Ключ сохранён в браузере</span>
            )}
          </div>

          <button
            className="btn btn-primary"
            onClick={handleUpdateDb}
            disabled={updating}
          >
            {updating ? 'Обновление…' : 'Обновить базу'}
          </button>
        </div>
        {updateMsg && <div className="update-msg">{updateMsg}</div>}
      </header>

      <main className="main">
        <Routes>
          <Route
            path="/"
            element={
              <CatalogPage selected={selected} onToggle={toggleSelect} />
            }
          />
          <Route path="/compare" element={<ComparePage />} />
        </Routes>
      </main>

      {selected.length >= 2 && (
        <div className="compare-bar">
          <div className="compare-bar-inner">
            <span>
              Выбрано: {selected.length} / 4
              {selected.length > 0 && (
                <span className="selected-names">
                  {' '}
                  ({selected.map((s) => s.name).join(', ')})
                </span>
              )}
            </span>
            <div className="compare-bar-actions">
              <button className="btn btn-ghost" onClick={clearSelection}>
                Очистить
              </button>
              <button className="btn btn-primary" onClick={goToCompare}>
                Перейти к сравнению
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
