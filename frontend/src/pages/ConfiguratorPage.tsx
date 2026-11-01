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

/** Ключи характеристик для сортировки/фильтра по категории */
const SPEC_SORT_KEYS: Record<string, { key: string; labels: string[] }[]> = {
  cpu: [
    { key: 'socket', labels: ['Сокет', 'Socket'] },
    { key: 'cores', labels: ['Общее количество ядер', 'Количество ядер', 'Cores'] },
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

function normalizeSocket(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/socket/gi, '')
    .replace(/сокет/gi, '')
    .replace(/\s+/g, '')
    .replace(/am5/g, 'am5')
    .replace(/am4/g, 'am4')
    .replace(/lga(\d+)/g, 'lga$1')
    .trim()
}

function extractDdr(raw: string): string {
  const m = raw.match(/ddr\s*([45])/i)
  return m ? `ddr${m[1]}` : ''
}

function socketsMatch(a: string, b: string): boolean {
  if (!a || !b) return true // нет данных — не режем список
  const na = normalizeSocket(a)
  const nb = normalizeSocket(b)
  if (!na || !nb) return true
  return na === nb || na.includes(nb) || nb.includes(na)
}

function ddrMatch(a: string, b: string): boolean {
  if (!a || !b) return true
  const da = extractDdr(a)
  const db = extractDdr(b)
  if (!da || !db) return true
  return da === db
}

function itemSocket(item: ComponentListItem): string {
  return specVal(item, ['Сокет', 'Socket'])
}

function itemMemType(item: ComponentListItem): string {
  return specVal(item, ['Тип памяти', 'Memory Type', 'DDR'])
}

/** Фильтр совместимости с уже выбранными слотами (порядок не важен) */
function isCompatibleWithBuild(
  slotKey: string,
  item: ComponentListItem,
  build: BuildMap,
): boolean {
  const cpu = build.cpu
  const mb = build.motherboard
  const ram = build.ram

  if (slotKey === 'cpu') {
    if (mb) {
      if (!socketsMatch(itemSocket(item), itemSocket(mb))) return false
    }
    // cooler with socket list — soft
    return true
  }

  if (slotKey === 'motherboard') {
    if (cpu && !socketsMatch(itemSocket(item), itemSocket(cpu))) return false
    if (ram && !ddrMatch(itemMemType(item), itemMemType(ram))) return false
    return true
  }

  if (slotKey === 'ram') {
    if (mb && !ddrMatch(itemMemType(item), itemMemType(mb))) return false
    return true
  }

  if (slotKey === 'cooler') {
    // если у кулера указан сокет — сверяем с CPU/MB
    const coolSock = itemSocket(item)
    if (coolSock) {
      if (cpu && !socketsMatch(coolSock, itemSocket(cpu))) return false
      if (mb && !socketsMatch(coolSock, itemSocket(mb))) return false
    }
    return true
  }

  return true
}

function checkCompat(build: BuildMap): string[] {
  const warns: string[] = []
  const cpu = build.cpu
  const mb = build.motherboard
  const ram = build.ram
  const psu = build.psu
  const gpu = build.gpu

  if (cpu && mb) {
    const sockCpu = itemSocket(cpu)
    const sockMb = itemSocket(mb)
    if (sockCpu && sockMb && !socketsMatch(sockCpu, sockMb)) {
      warns.push(`Сокет: процессор «${sockCpu}» и плата «${sockMb}» несовместимы`)
    }
  }
  if (mb && ram) {
    const typeMb = itemMemType(mb)
    const typeRam = itemMemType(ram)
    if (typeMb && typeRam && !ddrMatch(typeMb, typeRam)) {
      warns.push(`Память: плата «${typeMb}», модули «${typeRam}»`)
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

/** Уникальные значения характеристики среди списка (для фильтра) */
function facetValues(items: ComponentListItem[], labels: string[]): string[] {
  const set = new Map<string, number>()
  for (const it of items) {
    const v = specVal(it, labels).trim()
    if (!v) continue
    set.set(v, (set.get(v) || 0) + 1)
  }
  return [...set.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ru'))
    .map(([v]) => v)
    .slice(0, 30)
}

export function ConfiguratorPage() {
  const [categories, setCategories] = useState<Category[]>([])
  const [build, setBuild] = useState<BuildMap>(() => loadBuild())
  const [activeSlot, setActiveSlot] = useState<string | null>(null)
  /** Полный список категории из API */
  const [rawItems, setRawItems] = useState<ComponentListItem[]>([])
  const [pickerQ, setPickerQ] = useState('')
  const [pickerLoading, setPickerLoading] = useState(false)
  const [sort, setSort] = useState<SpecSort>('price_asc')
  /** Фильтры по характеристикам: key -> value */
  const [specFilters, setSpecFilters] = useState<Record<string, string>>({})

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
    try {
      // тянем максимум из базы категории
      const page = await fetchComponents({
        category: slotKey,
        limit: 120,
        sort: 'price_asc',
      })
      setRawItems(page.items)
    } catch {
      setRawItems([])
    } finally {
      setPickerLoading(false)
    }
  }, [])

  const openPicker = useCallback(
    async (slotKey: string) => {
      setActiveSlot(slotKey)
      setPickerQ('')
      setSpecFilters({})
      setSort('price_asc')
      await loadSlot(slotKey)
    },
    [loadSlot],
  )

  /** Совместимые с текущей сборкой */
  const compatibleItems = useMemo(() => {
    if (!activeSlot) return []
    return rawItems.filter((it) => isCompatibleWithBuild(activeSlot, it, build))
  }, [rawItems, activeSlot, build])

  /** Поиск + фильтры по характеристикам (по уже совместимым) */
  const filteredItems = useMemo(() => {
    let list = compatibleItems
    const q = pickerQ.trim().toLowerCase()
    if (q) {
      list = list.filter(
        (it) =>
          (it.name || '').toLowerCase().includes(q) ||
          (it.brand || '').toLowerCase().includes(q) ||
          (it.model || '').toLowerCase().includes(q),
      )
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
    const parts: string[] = []
    if (activeSlot === 'motherboard' || activeSlot === 'cpu' || activeSlot === 'cooler') {
      if (build.cpu) parts.push(`сокет CPU: ${itemSocket(build.cpu) || '—'}`)
      if (build.motherboard) parts.push(`сокет MB: ${itemSocket(build.motherboard) || '—'}`)
    }
    if (activeSlot === 'motherboard' || activeSlot === 'ram') {
      if (build.ram) parts.push(`память: ${itemMemType(build.ram) || '—'}`)
      if (build.motherboard) parts.push(`слоты MB: ${itemMemType(build.motherboard) || '—'}`)
    }
    if (!parts.length) return null
    return `Фильтр совместимости: ${parts.join(' · ')} · показано ${compatibleItems.length} из ${rawItems.length}`
  }, [activeSlot, build, compatibleItems.length, rawItems.length])

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
      <div className="cfg-header">
        <div>
          <h1>Конфигуратор ПК</h1>
          <p className="cfg-sub">
            Совместимость по сокету и типу памяти учитывается в любую сторону: можно начать с
            оперативки — платы отфильтруются под DDR, и наоборот.
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
                    <button
                      type="button"
                      className="btn btn-outline btn-sm"
                      onClick={() => void openPicker(slot.key)}
                    >
                      Заменить
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => clearSlot(slot.key)}
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
          )
        })}
      </div>

      {activeSlot && (
        <div className="cfg-picker-backdrop" onClick={() => setActiveSlot(null)}>
          <div className="cfg-picker" onClick={(e) => e.stopPropagation()}>
            <div className="cfg-picker-head">
              <h2>{catRu(activeSlot)}</h2>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setActiveSlot(null)}>
                ✕
              </button>
            </div>

            {compatNote && <div className="cfg-compat-note">{compatNote}</div>}

            <div className="cfg-picker-filters">
              <input
                type="search"
                placeholder="Поиск по названию…"
                value={pickerQ}
                onChange={(e) => setPickerQ(e.target.value)}
                autoFocus
              />
              <select value={sort} onChange={(e) => setSort(e.target.value as SpecSort)}>
                {sortOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Фильтры по характеристикам среди совместимых */}
            <div className="cfg-spec-filters">
              {(SPEC_SORT_KEYS[activeSlot] || []).map((s) => {
                const values = facetValues(compatibleItems, s.labels)
                if (values.length < 2) return null
                return (
                  <label key={s.key} className="cfg-spec-filter">
                    <span>{s.labels[0]}</span>
                    <select
                      value={specFilters[s.key] || ''}
                      onChange={(e) =>
                        setSpecFilters((prev) => ({
                          ...prev,
                          [s.key]: e.target.value,
                        }))
                      }
                    >
                      <option value="">Все</option>
                      {values.map((v) => (
                        <option key={v} value={v}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </label>
                )
              })}
            </div>

            <div className="cfg-picker-list">
              {pickerLoading && <div className="cfg-empty">Загрузка каталога…</div>}
              {!pickerLoading && filteredItems.length === 0 && (
                <div className="cfg-empty">
                  {compatibleItems.length === 0 && rawItems.length > 0
                    ? 'Нет совместимых позиций с текущей сборкой. Снимите конфликтующий слот или обновите базу.'
                    : 'Нет товаров. Обновите базу или измените поиск.'}
                </div>
              )}
              {!pickerLoading &&
                filteredItems.map((item) => (
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
                      <div className="cfg-brand">
                        {[item.brand, itemSocket(item) || itemMemType(item)]
                          .filter(Boolean)
                          .join(' · ')}
                      </div>
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
