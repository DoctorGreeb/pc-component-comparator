import { useState, useCallback } from 'react'
import { Routes, Route, Link, useNavigate } from 'react-router-dom'
import { CatalogPage } from './pages/CatalogPage'
import { ComparePage } from './pages/ComparePage'
import { updateDatabase } from './api'
import './App.css'

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
  const navigate = useNavigate()

  const toggleSelect = useCallback((item: SelectedItem) => {
    setSelected((prev) => {
      const exists = prev.find((s) => s.id === item.id)
      if (exists) {
        return prev.filter((s) => s.id !== item.id)
      }
      if (prev.length > 0 && prev[0].categoryId !== item.categoryId) {
        // Different category — reset and start new selection
        return [item]
      }
      if (prev.length >= 4) {
        return prev // max 4
      }
      return [...prev, item]
    })
  }, [])

  const clearSelection = () => setSelected([])

  const handleUpdateDb = async () => {
    setUpdating(true)
    setUpdateMsg(null)
    try {
      const res = await updateDatabase()
      setUpdateMsg(res.message)
    } catch {
      setUpdateMsg('Ошибка обновления базы')
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
          <button
            className="btn btn-outline"
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
              <CatalogPage
                selected={selected}
                onToggle={toggleSelect}
              />
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
