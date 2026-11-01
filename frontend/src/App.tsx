import { useState, useCallback, useEffect, useRef } from 'react'
import { Routes, Route, Link, useNavigate } from 'react-router-dom'
import { CatalogPage } from './pages/CatalogPage'
import { ComparePage } from './pages/ComparePage'
import { ConfiguratorPage } from './pages/ConfiguratorPage'
import { ProductPage } from './pages/ProductPage'
import { updateDatabaseWithProgress, exportCatalog, importCatalogWithProgress } from './api'
import {
  AppSettings,
  loadSettings,
  saveSettings,
  applyTheme,
  DEFAULT_SETTINGS,
} from './settings'
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
  const [progressPct, setProgressPct] = useState(0)
  const [progressOp, setProgressOp] = useState('')
  const [updateMsg, setUpdateMsg] = useState<string | null>(null)
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [apiKeyApplied, setApiKeyApplied] = useState(false)
  const [economy, setEconomy] = useState(false)
  const [creditsExhausted, setCreditsExhausted] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settings, setSettings] = useState<AppSettings>(() => loadSettings())
  const [draft, setDraft] = useState<AppSettings>(() => loadSettings())
  const fileRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      setApiKeyInput(saved)
      setApiKeyApplied(true)
    }
    applyTheme(settings.theme)
  }, [])

  useEffect(() => {
    applyTheme(settings.theme)
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      if (settings.theme === 'system') applyTheme('system')
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [settings.theme])

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

  const openSettings = () => {
    setDraft({ ...settings })
    setSettingsOpen(true)
  }

  const saveSettingsForm = () => {
    const next: AppSettings = {
      ...draft,
      imageTimeoutSec: Math.max(1, Math.min(99, Number(draft.imageTimeoutSec) || 15)),
      maxWebImages: Math.max(0, Math.min(500, Number(draft.maxWebImages) || 100)),
      pageSize: Math.max(12, Math.min(120, Number(draft.pageSize) || 48)),
    }
    setSettings(next)
    saveSettings(next)
    setSettingsOpen(false)
    setUpdateMsg('Настройки сохранены')
  }

  const runUpdate = async (opts: { freeOnly?: boolean; forceEconomy?: boolean }) => {
    const key = apiKeyInput.trim() || localStorage.getItem(STORAGE_KEY) || undefined
    const freeOnly = !!opts.freeOnly || !key
    setUpdating(true)
    setUpdateMsg(null)
    setProgressPct(1)
    setProgressOp('Запуск обновления…')
    try {
      const res = await updateDatabaseWithProgress(
        {
          apiKey: freeOnly ? undefined : key,
          economy: opts.forceEconomy ?? economy,
          freeOnly,
          imageTimeoutSec: settings.imageTimeoutSec,
          maxWebImages: settings.maxWebImages,
          webImages: settings.webImages,
          googleApiKey: settings.googleCseKey || undefined,
          googleCx: settings.googleCseCx || undefined,
        },
        (ev) => {
          setProgressPct(Math.max(0, Math.min(100, ev.pct ?? 0)))
          if (ev.op) setProgressOp(ev.op)
        },
      )
      setCreditsExhausted(!!res.credits_exhausted)
      setProgressPct(100)
      setProgressOp(res.status === 'error' ? 'Ошибка' : 'Готово')
      setUpdateMsg(res.message + (res.note ? ` — ${res.note}` : ''))
    } catch (e) {
      setProgressOp('Ошибка')
      setUpdateMsg(e instanceof Error ? e.message : 'Ошибка обновления базы')
    } finally {
      setUpdating(false)
    }
  }

  const handleFreeUpdate = () => void runUpdate({ freeOnly: true })
  const handleUpdateDb = (forceEconomy?: boolean) => void runUpdate({ forceEconomy })

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
      setUpdateMsg(`Экспорт: ${data.count} позиций.`)
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
      setUpdateMsg(null)
      setProgressPct(1)
      setProgressOp(`Чтение JSON: ${items.length} позиций…`)
      const res = await importCatalogWithProgress(items, (ev) => {
        setProgressPct(Math.max(0, Math.min(100, ev.pct ?? 0)))
        if (ev.op) setProgressOp(ev.op)
      })
      setProgressPct(100)
      setProgressOp('Готово')
      setUpdateMsg(res.message || `Импорт: +${res.added ?? res.components_added ?? 0}`)
      setCreditsExhausted(false)
    } catch (e) {
      setProgressOp('Ошибка')
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
          <Link to="/" className="logo">PC Comparator</Link>
          <nav className="nav">
            <Link to="/">Каталог</Link>
            <Link to="/configurator">Конфигуратор</Link>
          </nav>

          <div className="api-key-block">
            <div className="api-key-row">
              <label className="api-key-label" htmlFor="api-key-input">
                ReefAPI ключ
                <span className="help-tip" tabIndex={0}>
                  ?
                  <span className="help-tip-content">
                    Ключ — живые цены. Без ключа — open-data. Картинки: Google/DDG/Bing/Wiki.
                  </span>
                </span>
              </label>
              <input id="api-key-input" type="password" className="api-key-input" placeholder="ak_live_..."
                value={apiKeyInput} onChange={(e) => { setApiKeyInput(e.target.value); setApiKeyApplied(false) }} autoComplete="off" />
              <button type="button" className="btn btn-outline btn-sm" onClick={handleApplyKey}>Применить</button>
              <a className="btn btn-ghost btn-sm link-external" href={REEF_SIGNUP_URL} target="_blank" rel="noopener noreferrer">Получить ключ</a>
            </div>
            <div className="api-key-extra">
              <label className="economy-check">
                <input type="checkbox" checked={economy} onChange={(e) => setEconomy(e.target.checked)} />
                Экономный режим
              </label>
              {apiKeyApplied && <span className="api-key-status">Ключ в браузере</span>}
            </div>
          </div>

          <div className="header-actions">
            <button type="button" className="btn btn-outline btn-sm" onClick={openSettings} disabled={updating}>Настройки</button>
            <button className="btn btn-primary" onClick={() => handleUpdateDb()} disabled={updating}>{updating ? 'Обновление…' : 'Обновить базу'}</button>
            <button type="button" className="btn btn-outline" onClick={handleFreeUpdate} disabled={updating}>Без ключа</button>
            <button type="button" className="btn btn-outline btn-sm" onClick={handleExport} disabled={updating}>Экспорт</button>
            <button type="button" className="btn btn-outline btn-sm" onClick={() => fileRef.current?.click()} disabled={updating}>Импорт</button>
            <input ref={fileRef} type="file" accept="application/json,.json" hidden
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void handleImportFile(f); e.target.value = '' }} />
          </div>
        </div>

        {updating && (
          <div className="progress-panel" role="status" aria-live="polite">
            <div className="progress-panel-inner">
              <div className="progress-track"><div className="progress-fill" style={{ width: `${progressPct}%` }} /></div>
              <div className="progress-meta">
                <span className="progress-op">{progressOp || 'Обновление…'}</span>
                <span className="progress-pct">{Math.round(progressPct)}%</span>
              </div>
            </div>
          </div>
        )}

        {creditsExhausted && (
          <div className="credits-banner">
            <strong>Кредиты ReefAPI закончились.</strong>{' '}
            <a href={REEF_PRICING_URL} target="_blank" rel="noopener noreferrer">Пополнить</a> или «Без ключа».
          </div>
        )}

        {updateMsg && !updating && <div className="update-msg">{updateMsg}</div>}
      </header>

      <main className="main">
        <Routes>
          <Route path="/" element={<CatalogPage selected={selected} onToggle={toggleSelect} />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/configurator" element={<ConfiguratorPage />} />
          <Route path="/product/:id" element={<ProductPage />} />
        </Routes>
      </main>

      {selected.length >= 2 && (
        <div className="compare-bar">
          <div className="compare-bar-inner">
            <span>Выбрано: {selected.length} / 4<span className="selected-names"> ({selected.map((s) => s.name).join(', ')})</span></span>
            <div className="compare-bar-actions">
              <button className="btn btn-ghost" onClick={clearSelection}>Очистить</button>
              <button className="btn btn-primary" onClick={goToCompare}>Перейти к сравнению</button>
            </div>
          </div>
        </div>
      )}

      {settingsOpen && (
        <div className="modal-backdrop" onClick={() => setSettingsOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
            <div className="modal-header">
              <h2>Настройки</h2>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSettingsOpen(false)}>✕</button>
            </div>
            <div className="modal-body">
              <label className="field">
                <span>Тема сайта</span>
                <select value={draft.theme} onChange={(e) => setDraft({ ...draft, theme: e.target.value as AppSettings['theme'] })}>
                  <option value="light">Светлая</option>
                  <option value="dark">Тёмная</option>
                  <option value="system">Как в системе</option>
                </select>
              </label>

              <label className="field">
                <span>Таймаут поиска картинки (сек, 1–99)</span>
                <input type="number" min={1} max={99} value={draft.imageTimeoutSec}
                  onChange={(e) => setDraft({ ...draft, imageTimeoutSec: Math.max(1, Math.min(99, Number(e.target.value) || 1)) })} />
              </label>

              <label className="field">
                <span>Макс. товаров для web-поиска картинок</span>
                <input type="number" min={0} max={500} value={draft.maxWebImages}
                  onChange={(e) => setDraft({ ...draft, maxWebImages: Math.max(0, Math.min(500, Number(e.target.value) || 0)) })} />
              </label>

              <label className="field check">
                <input type="checkbox" checked={draft.webImages} onChange={(e) => setDraft({ ...draft, webImages: e.target.checked })} />
                <span>Искать картинки (Google / DDG / Bing / Wiki / Openverse)</span>
              </label>

              <label className="field">
                <span>Google CSE API key</span>
                <input type="password" value={draft.googleCseKey}
                  onChange={(e) => setDraft({ ...draft, googleCseKey: e.target.value })}
                  placeholder="AIza..." autoComplete="off" />
                <small>Без ключа — DDG/Bing/Wiki. С ключом — Google Images первым.</small>
              </label>

              <label className="field">
                <span>Google Search Engine ID (cx)</span>
                <input type="text" value={draft.googleCseCx}
                  onChange={(e) => setDraft({ ...draft, googleCseCx: e.target.value })}
                  placeholder="a1b2c3..." autoComplete="off" />
              </label>

              <label className="field">
                <span>Товаров на странице каталога</span>
                <input type="number" min={12} max={120} value={draft.pageSize}
                  onChange={(e) => setDraft({ ...draft, pageSize: Math.max(12, Math.min(120, Number(e.target.value) || 48)) })} />
              </label>

              <label className="field check">
                <input type="checkbox" checked={draft.compactCards} onChange={(e) => setDraft({ ...draft, compactCards: e.target.checked })} />
                <span>Компактные карточки</span>
              </label>

              <label className="field check">
                <input type="checkbox" checked={draft.showOrientirPrices} onChange={(e) => setDraft({ ...draft, showOrientirPrices: e.target.checked })} />
                <span>Показывать ориентировочные цены (open-data)</span>
              </label>

              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDraft({ ...DEFAULT_SETTINGS })}>
                Сбросить по умолчанию
              </button>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn btn-outline" onClick={() => setSettingsOpen(false)}>Отмена</button>
              <button type="button" className="btn btn-primary" onClick={saveSettingsForm}>Сохранить</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
