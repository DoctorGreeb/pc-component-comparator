import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Category,
  ComponentListItem,
  fetchCategories,
  fetchComponents,
  formatPrice,
} from '../api'
import './ConfiguratorPage.css'

const BUILD_KEY = 'pc_comparator_build'

/** Порядок слотов как в DNS-конфигураторе */
const SLOTS: { key: string; label: string; required?: boolean }[] = [
  { key: 'cpu', label: 'Процессор', required: true },
  { key: 'motherboard', label: 'Материнская плата', required: true },
  { key: 'ram', label: 'Оперативная память', required: true },
  { key: 'gpu', label: 'Видеокарта' },
  { key: 'ssd', label: 'SSD накопитель' },
  { key: 'hdd', label: 'HDD накопитель' },
  { key: 'cooler', label: 'Охлаждение' },
  { key: 'psu', label: 'Блок питания', required: true },
  { key: 'case', label: 'Корпус' },
]

type BuildMap = Record<string, ComponentListItem | null>

function loadBuild(): BuildMap {
  try {
    const raw = localStorage.getItem(BUILD_KEY)
    if (!raw) return Object.fromEntries(SLOTS.map((s) => [s.key, null]))
    const parsed = JSON.parse(raw) as BuildMap
    return Object.fromEntries(SLOTS.map((s) => [s.key, parsed[s.key] || null]))
  } catch {
    return Object.fromEntries(SLOTS.map((s) => [s.key, null]))
  }
}

function saveBuild(b: BuildMap) {
  localStorage.setItem(BUILD_KEY, JSON.stringify(b))
}

function specVal(item: ComponentListItem | null, keys: string[]): string {
  if (!item?.specs) return ''
  const specs = item.specs
  for (const k of keys) {
    for (const [ak, av] of Object.entries(specs)) {
      if (ak.toLowerCase().includes(k.toLowerCase()) || k.toLowerCase().includes(ak.toLowerCase())) {
        return String(av || '')
      }
    }
  }
  return ''
}

function checkCompat(build: BuildMap): string[] {
  const warns: string[] = []
  const cpu = build.cpu
  const mb = build.motherboard
  const ram = build.ram
  const psu = build.psu
  const gpu = build.gpu

  if (cpu && mb) {
    const sockCpu = specVal(cpu, ['Сокет', 'Socket'])
    const sockMb = specVal(mb, ['Сокет', 'Socket'])
    if (sockCpu && sockMb) {
      const a = sockCpu.toLowerCase().replace(/\s/g, '')
      const b = sockMb.toLowerCase().replace(/\s/g, '')
      if (!a.includes(b) && !b.includes(a) && a !== b) {
        warns.push(`Сокет: процессор «${sockCpu}» и плата «${sockMb}» могут быть несовместимы`)
      }
    }
  }

  if (mb && ram) {
    const typeMb = specVal(mb, ['Тип памяти', 'Memory Type', 'DDR'])
    const typeRam = specVal(ram, ['Тип памяти', 'Memory Type', 'DDR'])
    if (typeMb && typeRam) {
      const ddrMb = (typeMb.match(/ddr\s*\d/i) || [])[0]?.toLowerCase().replace(/\s/g, '')
      const ddrRam = (typeRam.match(/ddr\s*\d/i) || [])[0]?.toLowerCase().replace(/\s/g, '')
      if (ddrMb && ddrRam && ddrMb !== ddrRam) {
        warns.push(`Память: плата «${typeMb}», модули «${typeRam}»`)
      }
    }
  }

  if (psu && gpu) {
    const watt = parseInt(specVal(psu, ['Мощность', 'Wattage']).replace(/\D/g, ''), 10)
    if (watt && watt < 450) {
      warns.push(`БП ${watt} Вт может быть слабоват для связки с видеокартой`)
    }
  }

  return warns
}

export function ConfiguratorPage() {
  const [categories, setCategories] = useState<Category[]>([])
  const [build, setBuild] = useState<BuildMap>(() => loadBuild())
  const [activeSlot, setActiveSlot] = useState<string | null>(null)
  const [pickerItems, setPickerItems] = useState<ComponentListItem[]>([])
  const [pickerQ, setPickerQ] = useState('')
  const [pickerLoading, setPickerLoading] = useState(false)
  const [sort, setSort] = useState<'price_asc' | 'price_desc'>('price_asc')

  useEffect(() => {
    void fetchCategories().then(setCategories).catch(() => {})
  }, [])

  useEffect(() => {
    saveBuild(build)
  }, [build])

  const total = useMemo(() => {
    return SLOTS.reduce((sum, s) => {
      const p = build[s.key]?.min_price
      return sum + (p != null ? p : 0)
    }, 0)
  }, [build])

  const filled = useMemo(
    () => SLOTS.filter((s) => build[s.key]).length,
    [build],
  )

  const warnings = useMemo(() => checkCompat(build), [build])

  const openPicker = useCallback(
    async (slotKey: string) => {
      setActiveSlot(slotKey)
      setPickerQ('')
      setPickerLoading(true)
      try {
        const page = await fetchComponents({
          category: slotKey,
          sort,
          limit: 60,
        })
        setPickerItems(page.items)
      } catch {
        setPickerItems([])
      } finally {
        setPickerLoading(false)
      }
    },
    [sort],
  )

  const searchPicker = async () => {
    if (!activeSlot) return
    setPickerLoading(true)
    try {
      const page = await fetchComponents({
        category: activeSlot,
        q: pickerQ || undefined,
        sort,
        limit: 60,
      })
      setPickerItems(page.items)
    } catch {
      setPickerItems([])
    } finally {
      setPickerLoading(false)
    }
  }

  const selectPart = (item: ComponentListItem) => {
    if (!activeSlot) return
    setBuild((prev) => ({ ...prev, [activeSlot]: item }))
    setActiveSlot(null)
  }

  const clearSlot = (key: string) => {
    setBuild((prev) => ({ ...prev, [key]: null }))
  }

  const clearAll = () => {
    setBuild(Object.fromEntries(SLOTS.map((s) => [s.key, null])))
  }

  const catRu = (key: string) =>
    categories.find((c) => c.name === key)?.name_ru ||
    SLOTS.find((s) => s.key === key)?.label ||
    key

  return (
    <div className="cfg">
      <div className="cfg-header">
        <div>
          <h1>Конфигуратор ПК</h1>
          <p className="cfg-sub">
            Соберите системный блок по слотам, как в DNS. Совместимость сокета и памяти
            проверяется по характеристикам из базы.
          </p>
        </div>
        <div className="cfg-summary">
          <div className="cfg-total">
            <span>Итого</span>
            <strong>{formatPrice(total || null)}</strong>
          </div>
          <div className="cfg-filled">
            {filled} / {SLOTS.length} позиций
          </div>
          <button type="button" className="btn btn-outline btn-sm" onClick={clearAll}>
            Очистить сборку
          </button>
        </div>
      </div>

      {warnings.length > 0 && (
        <div className="cfg-warnings">
          <strong>Проверьте совместимость:</strong>
          <ul>
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="cfg-slots">
        {SLOTS.map((slot) => {
          const item = build[slot.key]
          return (
            <div key={slot.key} className={`cfg-slot ${item ? 'filled' : ''}`}>
              <div className="cfg-slot-label">
                {slot.label}
                {slot.required && <span className="req">*</span>}
              </div>
              {item ? (
                <div className="cfg-slot-item">
                  {item.image_url && (
                    <img src={item.image_url} alt="" className="cfg-thumb" loading="lazy" />
                  )}
                  <div className="cfg-slot-meta">
                    <div className="cfg-name">{item.name}</div>
                    <div className="cfg-price">{formatPrice(item.min_price)}</div>
                  </div>
                  <div className="cfg-slot-actions">
                    <button type="button" className="btn btn-outline btn-sm" onClick={() => void openPicker(slot.key)}>
                      Заменить
                    </button>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => clearSlot(slot.key)}>
                      ✕
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  className="cfg-add"
                  onClick={() => void openPicker(slot.key)}
                >
                  + Выбрать {slot.label.toLowerCase()}
                </button>
              )}
            </div>
          )
        })}
      </div>

      {activeSlot && (
        <div className="cfg-picker-backdrop" onClick={() => setActiveSlot(null)}>
          <div className="cfg-picker" onClick={(e) => e.stopPropagation()}>
            <div className="cfg-picker-head">
              <h2>{catRu(activeSlot)}</h2>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setActiveSlot(null)}>✕</button>
            </div>
            <div className="cfg-picker-filters">
              <input
                type="search"
                placeholder="Поиск в категории…"
                value={pickerQ}
                onChange={(e) => setPickerQ(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void searchPicker()}
              />
              <select
                value={sort}
                onChange={(e) => {
                  setSort(e.target.value as 'price_asc' | 'price_desc')
                }}
              >
                <option value="price_asc">Сначала дешёвые</option>
                <option value="price_desc">Сначала дорогие</option>
              </select>
              <button type="button" className="btn btn-primary btn-sm" onClick={() => void searchPicker()}>
                Найти
              </button>
            </div>
            <div className="cfg-picker-list">
              {pickerLoading && <div className="cfg-empty">Загрузка…</div>}
              {!pickerLoading && pickerItems.length === 0 && (
                <div className="cfg-empty">Нет товаров. Обновите базу или смените запрос.</div>
              )}
              {!pickerLoading &&
                pickerItems.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className="cfg-picker-row"
                    onClick={() => selectPart(item)}
                  >
                    {item.image_url ? (
                      <img src={item.image_url} alt="" loading="lazy" />
                    ) : (
                      <div className="cfg-picker-noimg" />
                    )}
                    <div className="cfg-picker-meta">
                      <div className="cfg-name">{item.name}</div>
                      {item.brand && <div className="cfg-brand">{item.brand}</div>}
                    </div>
                    <div className="cfg-price">{formatPrice(item.min_price)}</div>
                  </button>
                ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
