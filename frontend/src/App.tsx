import { useState, useCallback, useEffect, useRef } from 'react'
import { Routes, Route, Link, useNavigate } from 'react-router-dom'
import { CatalogPage } from './pages/CatalogPage'
import { ComparePage } from './pages/ComparePage'
import { updateDatabase, exportCatalog, importCatalog } from './api'
import './App.css'

const STORAGE_KEY = 'reefapi_key'
const REEF_SIGNUP_URL = 'https://reefapi.com/signup'
const REEF_PRICING_URL = 'https://reefapi.com/pricing'

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
  const [economy, setEconomy] = useState(false)
  const [creditsExhausted, setCreditsExhausted] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
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
      if (exists) return prev.filter((s) => s.id !== item.id)
      if (prev.length > 0 && prev[0].categoryId !== item.categoryId) return [item]
      if (prev.length >= 4) return prev
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
    setCreditsExhausted(false)
    setUpdateMsg('Ключ сохранён. Можно обновить базу.')
  }

  const handleUpdateDb = async (forceEconomy?: boolean) => {
    const key = apiKeyInput.trim() || localStorage.getItem(STORAGE_KEY) || undefined
    if (!key) {
      setUpdateMsg('Нет ключа: введите ReefAPI-ключ или импортируйте JSON-каталог.')
      return
    }
    const useEconomy = forceEconomy ?? economy
    setUpdating(true)
    setUpdateMsg(null)
    try {
      const res = await updateDatabase(key, useEconomy)
      setCreditsExhausted(!!res.credits_exhausted)
      setUpdateMsg(res.message + (res.note ? ` — ${res.note}` : ''))
    } catch (e) {
      setUpdateMsg(e instanceof Error ? e.message : 'Ошибка обновления базы')
    } finally {
      setUpdating(false)
    }
  }

  const handleExport = async () => {
    try {
      const data = await exportCatalog()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `pc-catalog-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
      setUpdateMsg(`Экспорт: ${data.count} позиций. Файл можно импортировать без API.`)
    } catch (e) {
      setUpdateMsg(e instanceof Error ? e.message : 'Ошибка экспорта')
    }
  }

  const handleImportFile = async (file: File) => {
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      const items = Array.isArray(data) ? data : data.items
      if (!Array.isArray(items) || !items.length) {
        setUpdateMsg('В JSON нет массива items')
        return
      }
      setUpdating(true)
      const res = await importCatalog(items)
      setUpdateMsg(res.message)
      setCreditsExhausted(false)
    } catch (e) {
      setUpdateMsg(e instanceof Error ? e.message : 'Ошибка импорта')
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
                    Ключ нужен для подгрузки цен DNS. Если кредиты кончились —
                    приложение продолжит работать на уже загруженных данных.
                    Можно экспортировать каталог в JSON и импортировать позже
                    без API, либо включить экономный режим (меньше запросов).
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
              <a className="btn btn-ghost btn-sm link-external" href={REEF_SIGNUP_URL} target="_blank" rel="noopener noreferrer">
                Получить ключ
              </a>
            </div>
            <div className="api-key-extra">
              <label className="economy-check">
                <input
                  type="checkbox"
                  checked={economy}
                  onChange={(e) => setEconomy(e.target.checked)}
                />
                Экономный режим (мало кредитов)
              </label>
              {apiKeyApplied && <span className="api-key-status">Ключ в браузере</span>}
            </div>
          </div>

          <div className="header-actions">
            <button className="btn btn-primary" onClick={() => handleUpdateDb()} disabled={updating}>
              {updating ? 'Обновление…' : 'Обновить базу'}
            </button>
            <button type="button" className="btn btn-outline btn-sm" onClick={handleExport} disabled={updating}>
              Экспорт JSON
            </button>
            <button
              type="button"
              className="btn btn-outline btn-sm"
              onClick={() => fileRef.current?.click()}
              disabled={updating}
            >
              Импорт JSON
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="application/json,.json"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) void handleImportFile(f)
                e.target.value = ''
              }}
            />
          </div>
        </div>

        {creditsExhausted && (
          <div className="credits-banner">
            <strong>Кредиты ReefAPI закончились.</strong>{' '}
            Каталог не стёрт — сравнение работает на уже загруженных товарах.{' '}
            <button type="button" className="linkish" onClick={() => handleUpdateDb(true)}>
              Экономное обновление
            </button>
            {' · '}
            <a href={REEF_PRICING_URL} target="_blank" rel="noopener noreferrer">
              Пополнить
            </a>
            {' · '}
            <button type="button" className="linkish" onClick={handleExport}>
              Экспорт JSON
            </button>
          </div>
        )}

        {updateMsg && <div className="update-msg">{updateMsg}</div>}
      </header>

      <main className="main">
        <Routes>
          <Route path="/" element={<CatalogPage selected={selected} onToggle={toggleSelect} />} />
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
                  {' '}({selected.map((s) => s.name).join(', ')})
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
