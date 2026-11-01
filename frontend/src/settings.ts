export type ThemeMode = 'light' | 'dark' | 'system'

export interface AppSettings {
  theme: ThemeMode
  /** Таймаут поиска одной картинки, 1–99 сек */
  imageTimeoutSec: number
  /** Макс. товаров для web-поиска картинок за один апдейт */
  maxWebImages: number
  /** Искать картинки в интернете, если нет донора */
  webImages: boolean
  /** Товаров на странице каталога */
  pageSize: number
  /** Компактные карточки */
  compactCards: boolean
  /** Показывать ориентировочные цены (open-data) */
  showOrientirPrices: boolean
  /** Автоматически обновлять каталог при открытии (не рекомендуется) */
  autoRefreshOnOpen: boolean
  /** Пауза после сообщения о таймауте картинки (сек, только UI-подсказка) */
  timeoutMessageHoldSec: number
}

export const DEFAULT_SETTINGS: AppSettings = {
  theme: 'system',
  imageTimeoutSec: 15,
  maxWebImages: 100,
  webImages: true,
  pageSize: 48,
  compactCards: false,
  showOrientirPrices: true,
  autoRefreshOnOpen: false,
  timeoutMessageHoldSec: 2,
}

const KEY = 'pc_comparator_settings'

export function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return { ...DEFAULT_SETTINGS }
    const parsed = JSON.parse(raw) as Partial<AppSettings>
    return {
      ...DEFAULT_SETTINGS,
      ...parsed,
      imageTimeoutSec: clamp(Number(parsed.imageTimeoutSec ?? 15), 1, 99),
      maxWebImages: clamp(Number(parsed.maxWebImages ?? 100), 0, 500),
      pageSize: clamp(Number(parsed.pageSize ?? 48), 12, 120),
      timeoutMessageHoldSec: clamp(Number(parsed.timeoutMessageHoldSec ?? 2), 0, 5),
    }
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

export function saveSettings(s: AppSettings): void {
  localStorage.setItem(KEY, JSON.stringify(s))
  applyTheme(s.theme)
}

function clamp(n: number, min: number, max: number): number {
  if (Number.isNaN(n)) return min
  return Math.max(min, Math.min(max, Math.round(n)))
}

export function applyTheme(theme: ThemeMode): void {
  const root = document.documentElement
  let resolved: 'light' | 'dark' = 'light'
  if (theme === 'dark') resolved = 'dark'
  else if (theme === 'light') resolved = 'light'
  else {
    resolved = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  root.setAttribute('data-theme', resolved)
}

export function settingsToApiPayload(s: AppSettings) {
  return {
    image_timeout_sec: s.imageTimeoutSec,
    max_web_images: s.maxWebImages,
    web_images: s.webImages,
  }
}
