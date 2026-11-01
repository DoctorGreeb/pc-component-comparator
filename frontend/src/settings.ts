export type ThemeMode = 'light' | 'dark' | 'system'

export interface AppSettings {
  theme: ThemeMode
  imageTimeoutSec: number
  maxWebImages: number
  webImages: boolean
  pageSize: number
  compactCards: boolean
  showOrientirPrices: boolean
  showSyncLogs: boolean
  autoRefreshOnOpen: boolean
  timeoutMessageHoldSec: number
  /** Google Custom Search API key (Programmable Search) */
  googleCseKey: string
  /** Search engine ID (cx) */
  googleCseCx: string
}

export const DEFAULT_SETTINGS: AppSettings = {
  theme: 'system',
  imageTimeoutSec: 8,
  maxWebImages: 80,
  webImages: true,
  pageSize: 48,
  compactCards: false,
  showOrientirPrices: true,
  showSyncLogs: true,
  autoRefreshOnOpen: false,
  timeoutMessageHoldSec: 1,
  googleCseKey: '',
  googleCseCx: '',
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
      imageTimeoutSec: clamp(Number(parsed.imageTimeoutSec ?? 8), 1, 99),
      maxWebImages: clamp(Number(parsed.maxWebImages ?? 80), 0, 500),
      pageSize: clamp(Number(parsed.pageSize ?? 48), 12, 120),
      timeoutMessageHoldSec: clamp(Number(parsed.timeoutMessageHoldSec ?? 1), 0, 5),
      googleCseKey: String(parsed.googleCseKey ?? ''),
      googleCseCx: String(parsed.googleCseCx ?? ''),
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
  document.body?.setAttribute('data-theme', resolved)
}

export function settingsToApiPayload(s: AppSettings) {
  return {
    image_timeout_sec: s.imageTimeoutSec,
    max_web_images: s.maxWebImages,
    web_images: s.webImages,
    google_api_key: s.googleCseKey || undefined,
    google_cx: s.googleCseCx || undefined,
  }
}
