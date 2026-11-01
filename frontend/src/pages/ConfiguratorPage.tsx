import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Category,
  ComponentListItem,
  fetchCategories,
  fetchComponents,
  formatPrice,
} from '../api'
import './ConfiguratorPage.css'
import {
  isCompatibleWithBuild,
  checkCompat,
  ddrLockMessage,
} from './configCompat'

const BUILD_KEY = 'pc_comparator_build'

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

const SPEC_SORT_KEYS: Record<string, { key: string; labels: string[] }[]> = {
  cpu: [
    { key: 'socket', labels: ['Сокет', 'Socket'] },
    { key: 'cores', labels: ['Общее количество ядер', 'Количество ядер', 'Cores', 'Ядра'] },
    { key: 'freq', labels: ['Максимальная частота', 'Базовая частота', 'Boost'] },
    { key: 'tdp', labels: ['Тепловыделение', 'TDP'] },
  ],
  motherboard: [
    { key: 'socket', labels: ['Сокет', 'Socket'] },
    { key: 'chipset', labels: ['Чипсет', 'Chipset'] },
    { key: 'mem', labels: ['Тип памяти', 'Memory Type', 'DDR'] },
    { key: 'form', labels: ['Форм-фактор', 'Form Factor'] },
  ],
  ram: [
    { key: 'mem', labels: ['Тип памяти', 'Memory Type', 'DDR'] },
    { key: 'size', labels: ['Суммарный объем', 'Объем', 'Capacity'] },
    { key: 'freq', labels: ['Тактовая частота', 'Frequency', 'МГц'] },
  ],
  gpu: [
    { key: 'vram', labels: ['Объем видеопамяти', 'Memory'] },
    { key: 'chip', labels: ['Графический чип', 'Графический процессор', 'Chipset'] },
  ],
  ssd: [
    { key: 'size', labels: ['Объем', 'Capacity'] },
    { key: 'iface', labels: ['Интерфейс', 'Interface'] },
  ],
  hdd: [
    { key: 'size', labels: ['Объем', 'Capacity'] },
    { key: 'rpm', labels: ['Скорость вращения', 'RPM'] },
  ],
  psu: [{ key: 'watt', labels: ['Мощность', 'Wattage'] }],
  case: [{ key: 'form', labels: ['Форм-фактор', 'Form Factor'] }],
  cooler: [
    { key: 'socket', labels: ['Сокет', 'Socket'] },
    { key: 'tdp', labels: ['TDP', 'Тепловыделение'] },
  ],
}

const ROW_SPEC_LABELS: Record<string, string[]> = {
  cpu: ['Сокет', 'Общее количество ядер', 'Количество ядер', 'Максимальная частота', 'Тепловыделение'],
  motherboard: ['Сокет', 'Чипсет', 'Тип памяти', 'Форм-фактор'],
  ram: ['Тип памяти', 'Суммарный объем', 'Объем', 'Тактовая частота'],
  gpu: ['Графический чип', 'Графический процессор', 'Объем видеопамяти'],
  ssd: ['Объем', 'Интерфейс', 'Тип'],
  hdd: ['Объем', 'Скорость вращения'],
  psu: ['Мощность', 'Сертификат 80 PLUS'],
  case: ['Форм-фактор', 'Цвет'],
  cooler: ['Тип', 'TDP', 'Сокет'],
}

type BuildMap = Record<string, ComponentListItem | null>
type SpecSort =
  | 'price_asc'
  | 'price_desc'
  | 'name_asc'
  | `spec:${string}:asc`
  | `spec:${string}:desc`

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

function specVal(item: ComponentListItem | null | undefined, labels: string[]): string {
  if (!item?.specs) return ''
  for (const k of labels) {
    for (const [ak, av] of Object.entries(item.specs)) {
      const a = ak.toLowerCase()
      const b = k.toLowerCase()
      if (a === b || a.includes(b) || b.includes(a)) return String(av || '')
    }
  }
  return ''
}

function rowSpecsLine(item: ComponentListItem, slotKey: string): string {
  const preferred = ROW_SPEC_LABELS[slotKey] || []
  const parts: string[] = []
  const used = new Set<string>()
  for (const lab of preferred) {
    const v = specVal(item, [lab])
    if (v && !used.has(v)) {
      parts.push(v)
      used.add(v)
    }
  }
  if (parts.length < 2 && item.specs) {
    for (const [k, v] of Object.entries(item.specs)) {
      if (!v) continue
      const s = String(v)
      if (used.has(s)) continue
      parts.push(`${k}: ${s}`)
      used.add(s)
      if (parts.length >= 4) break
    }
  }
  return parts.slice(0, 4).join(' · ')
}

function parseSpecNumber(raw: string): number {
  const m = raw.replace(',', '.').match(/[\d.]+/)
  return m ? parseFloat(m[0]) : NaN
}

function sortItems(items: ComponentListItem[], sort: SpecSort, slotKey: string): ComponentListItem[] {
  const arr = [...items]
  if (sort === 'price_asc') {
    arr.sort((a, b) => (a.min_price ?? 1e18) - (b.min_price ?? 1e18))
  } else if (sort === 'price_desc') {
    arr.sort((a, b) => (b.min_price ?? -1) - (a.min_price ?? -1))
  } else if (sort === 'name_asc') {
    arr.sort((a, b) => (a.name || '').localeCompare(b.name || '', 'ru'))
  } else if (sort.startsWith('spec:')) {
    const [, specKey, dir] = sort.split(':')
    const meta = (SPEC_SORT_KEYS[slotKey] || []).find((s) => s.key === specKey)
    const labels = meta?.labels || [specKey]
    arr.sort((a, b) => {
      const va = specVal(a, labels)
      const vb = specVal(b, labels)
      const na = parseSpecNumber(va)
      const nb = parseSpecNumber(vb)
      let cmp = 0
      if (!Number.isNaN(na) && !Number.isNaN(nb)) cmp = na - nb
      else cmp = va.localeCompare(vb, 'ru')
      return dir === 'desc' ? -cmp : cmp
    })
  }
  return arr
}

async function fetchAllInCategory(category: string): Promise<ComponentListItem[]> {
  const pageSize = 120
  let skip = 0
  let total = Infinity
  const all: ComponentListItem[] = []
  const seen = new Set<number>()

  while (skip < total && skip < 5000) {
    const page = await fetchComponents({
      category,
      limit: pageSize,
      skip,
      sort: 'price_asc',
    })
    total = page.total
    for (const it of page.items) {
      if (!seen.has(it.id)) {
        seen.add(it.id)
        all.push(it)
      }
    }
    if (page.items.length === 0) break
    skip += page.items.length
    if (skip >= total) break
  }
  return all
}

export function ConfiguratorPage() {
  const [categories, setCategories] = useState<Category[]>([])
  const [build, setBuild] = useState<BuildMap>(() => loadBuild())
  const [activeSlot, setActiveSlot] = useState<string | null>(null)
  const [rawItems, setRawItems] = useState<ComponentListItem[]>([])
  const [pickerQ, setPickerQ] = useState('')
  const [pickerLoading, setPickerLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [sort, setSort] = useState<SpecSort>('price_asc')
  const [specFilters, setSpecFilters] = useState<Record<string, string>>({})
  const [compatOnly, setCompatOnly] = useState(true)

  useEffect(() => {
    void fetchCategories().then(setCategories).catch(() => {})
  }, [])

  useEffect(() => {
    saveBuild(build)
  }, [build])

  const total = useMemo(
    () => SLOTS.reduce((sum, s) => sum + (build[s.key]?.min_price ?? 0), 0),
    [build],
  )
  const filled = useMemo(() => SLOTS.filter((s) => build[s.key]).length, [build])
  const warnings = useMemo(() => checkCompat(build), [build])

  const loadSlot = useCallback(async (slotKey: string) => {
    setPickerLoading(true)
    setLoadError(null)
    try {
      const items = await fetchAllInCategory(slotKey)
      setRawItems(items)
      if (items.length === 0) {
        setLoadError('В базе нет товаров этой категории. Обновите базу.')
      }
    } catch (e) {
      setRawItems([])
      setLoadError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setPickerLoading(false)
    }
  }, [])

  const openPicker = useCallback(
    async (slotKey: string) => {
      if (activeSlot === slotKey) {
        setActiveSlot(null)
        return
      }
      setActiveSlot(slotKey)
      setPickerQ('')
      setSpecFilters({})
      setSort('price_asc')
      setCompatOnly(true)
      await loadSlot(slotKey)
    },
    [loadSlot, activeSlot],
  )

  const compatibleItems = useMemo(() => {
    if (!activeSlot) return []
    if (!compatOnly) return rawItems
    return rawItems.filter((it) => isCompatibleWithBuild(activeSlot, it, build))
  }, [rawItems, activeSlot, build, compatOnly])

  const filteredItems = useMemo(() => {
    let list = compatibleItems
    const q = pickerQ.trim().toLowerCase()
    if (q) {
      list = list.filter((it) => {
        const blob = [
          it.name,
          it.brand,
          it.model,
          it.description,
          rowSpecsLine(it, activeSlot || ''),
          ...(it.specs ? Object.values(it.specs) : []),
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
        return blob.includes(q)
      })
    }
    if (activeSlot) {
      for (const [sk, val] of Object.entries(specFilters)) {
        if (!val) continue
        const meta = (SPEC_SORT_KEYS[activeSlot] || []).find((s) => s.key === sk)
        if (!meta) continue
        list = list.filter((it) => {
          const v = specVal(it, meta.labels)
          return v === val || v.toLowerCase().includes(val.toLowerCase())
        })
      }
    }
    return sortItems(list, sort, activeSlot || '')
  }, [compatibleItems, pickerQ, specFilters, sort, activeSlot])

  const compatNote = useMemo(() => {
    if (!activeSlot) return null
    return `В категории ${rawItems.length} шт. · после совместимости ${compatibleItems.length} · в списке ${filteredItems.length}`
  }, [activeSlot, rawItems.length, compatibleItems.length, filteredItems.length])

  const ddrLockNote = useMemo(
    () => ddrLockMessage(build, activeSlot),
    [build, activeSlot],
  )

  const selectPart = (item: ComponentListItem) => {
    if (!activeSlot) return
    setBuild((prev) => ({ ...prev, [activeSlot]: item }))
    setActiveSlot(null)
  }

  const clearSlot = (key: string) => setBuild((prev) => ({ ...prev, [key]: null }))
  const clearAll = () => setBuild(Object.fromEntries(SLOTS.map((s) => [s.key, null])))

  const catRu = (key: string) =>
    categories.find((c) => c.name === key)?.name_ru ||
    SLOTS.find((s) => s.key === key)?.label ||
    key

  const sortOptions = useMemo(() => {
    const base: { value: SpecSort; label: string }[] = [
      { value: 'price_asc', label: 'Цена ↑' },
      { value: 'price_desc', label: 'Цена ↓' },
      { value: 'name_asc', label: 'Название' },
    ]
    if (!activeSlot) return base
    for (const s of SPEC_SORT_KEYS[activeSlot] || []) {
      base.push({ value: `spec:${s.key}:asc`, label: `${s.labels[0]} ↑` })
      base.push({ value: `spec:${s.key}:desc`, label: `${s.labels[0]} ↓` })
    }
    return base
  }, [activeSlot])

  return (
    <div className="cfg">
      <header className="cfg-header">
        <div className="cfg-header-text">
          <h1>Конфигуратор ПК</h1>
          <p className="cfg-sub">
            Совместимость фильтрует список: AM5 → только DDR5, AM4 → только DDR4.
            Сокет процессора и платы должен совпадать.
          </p>
        </div>
        <div className="cfg-summary">
          <div className="cfg-total">
            <span>Итого</span>
            <strong>{formatPrice(total || null)}</strong>
          </div>
          <div className="cfg-filled">
            {filled} / {SLOTS.length}
          </div>
          <button type="button" className="btn btn-outline btn-sm" onClick={clearAll}>
            Очистить
          </button>
        </div>
      </header>

      {warnings.length > 0 && (
        <div className="cfg-warnings" role="alert">
          <strong>Проверьте совместимость</strong>
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
          const isOpen = activeSlot === slot.key
          return (
            <div
              key={slot.key}
              className={`cfg-slot ${item ? 'filled' : ''} ${isOpen ? 'open' : ''}`}
            >
              <div className="cfg-slot-top">
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
                      <div className="cfg-row-specs">{rowSpecsLine(item, slot.key)}</div>
                      <div className="cfg-price">{formatPrice(item.min_price)}</div>
                    </div>
                    <div className="cfg-slot-actions">
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        onClick={() => void openPicker(slot.key)}
                      >
                        {isOpen ? 'Свернуть' : 'Заменить'}
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => clearSlot(slot.key)}
                        aria-label="Убрать"
                      >
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

              {isOpen && (
                <div className="cfg-picker-panel">
                  <div className="cfg-picker-head">
                    <h2>Выбор: {catRu(slot.key)}</h2>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => setActiveSlot(null)}
                    >
                      Закрыть
                    </button>
                  </div>

                  {ddrLockNote && (
                    <div className="cfg-ddr-lock" role="status">
                      {ddrLockNote}
                    </div>
                  )}
                  {compatNote && <div className="cfg-compat-note">{compatNote}</div>}

                  <div className="cfg-picker-bar">
                    <input
                      type="search"
                      placeholder="Поиск по названию…"
                      value={pickerQ}
                      onChange={(e) => setPickerQ(e.target.value)}
                      autoFocus
                    />
                    <select
                      value={sort}
                      onChange={(e) => setSort(e.target.value as SpecSort)}
                    >
                      {sortOptions.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    <label className="cfg-compat-toggle">
                      <input
                        type="checkbox"
                        checked={compatOnly}
                        onChange={(e) => setCompatOnly(e.target.checked)}
                      />
                      Только совместимые
                    </label>
                  </div>

                  {pickerLoading && (
                    <div className="cfg-loading">Загрузка категории…</div>
                  )}
                  {loadError && <div className="cfg-error">{loadError}</div>}

                  {!pickerLoading && filteredItems.length === 0 && (
                    <div className="cfg-empty">
                      {compatOnly
                        ? 'Нет совместимых позиций. Снимите «Только совместимые» или смените уже выбранные слоты.'
                        : 'Ничего не найдено.'}
                    </div>
                  )}

                  {!pickerLoading && filteredItems.length > 0 && (
                    <div className="cfg-list">
                      {filteredItems.map((it) => (
                        <button
                          key={it.id}
                          type="button"
                          className="cfg-row"
                          onClick={() => selectPart(it)}
                        >
                          {it.image_url ? (
                            <img src={it.image_url} alt="" loading="lazy" />
                          ) : (
                            <div className="cfg-row-ph" />
                          )}
                          <div className="cfg-row-main">
                            <div className="cfg-row-name">{it.name}</div>
                            <div className="cfg-row-specs">
                              {rowSpecsLine(it, slot.key)}
                            </div>
                          </div>
                          <div className="cfg-row-price">
                            {formatPrice(it.min_price)}
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
