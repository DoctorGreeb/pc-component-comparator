const API_BASE = '/api';

export interface Category {
  id: number;
  name: string;
  name_ru: string;
}

export interface ComponentListItem {
  id: number;
  name: string;
  brand: string | null;
  model: string | null;
  image_url: string | null;
  category_id: number;
  category_name: string | null;
  description: string | null;
  min_price: number | null;
  old_price: number | null;
  product_url: string | null;
  specs: Record<string, string> | null;
}

export interface ComponentsPage {
  items: ComponentListItem[];
  total: number;
  skip: number;
  limit: number;
}

export interface FacetValue {
  value: string;
  count: number;
}

export interface Facet {
  key: string;
  values: FacetValue[];
}

export interface FacetsResponse {
  brands: FacetValue[];
  specs: Facet[];
  price_min: number | null;
  price_max: number | null;
}

export interface ComponentDetail {
  id: number;
  name: string;
  brand: string | null;
  model: string | null;
  description: string | null;
  image_url: string | null;
  specs: Record<string, unknown> | string | null;
  category_id: number;
  category?: Category;
  prices: Array<{
    id: number;
    price: number | null;
    old_price: number | null;
    in_stock: boolean;
    product_url: string | null;
    store?: { id: number; name: string; url: string | null };
  }>;
}

export type SortOption = 'price_asc' | 'price_desc' | 'name_asc' | 'name_desc';

export interface UpdateResult {
  status: string;
  message: string;
  note?: string;
  components_added: number;
  categories_ready?: number;
  economy?: boolean;
  credits_exhausted?: boolean;
  added?: number;
  updated?: number;
}

export interface ProgressEvent {
  pct: number;
  op: string;
  result?: UpdateResult;
  error?: string;
}

export interface ProductReviewSnippet {
  title: string;
  snippet: string;
  url: string;
  query?: string;
}

export interface ProductEnrichment {
  description: string | null;
  description_source: string | null;
  description_url: string | null;
  manufacturer_home: string | null;
  manufacturer_model_url: string | null;
  web_search_url: string | null;
  reviews: ProductReviewSnippet[];
  reviews_note: string;
}

export async function fetchCategories(): Promise<Category[]> {
  const res = await fetch(`${API_BASE}/categories`);
  if (!res.ok) throw new Error('Не удалось загрузить категории');
  return res.json();
}

export async function fetchComponents(params: {
  category?: string;
  q?: string;
  sort?: SortOption;
  brand?: string;
  price_min?: number;
  price_max?: number;
  spec?: string[];
  skip?: number;
  limit?: number;
}): Promise<ComponentsPage> {
  const search = new URLSearchParams();
  if (params.category) search.set('category', params.category);
  if (params.q) search.set('q', params.q);
  if (params.sort) search.set('sort', params.sort);
  if (params.brand) search.set('brand', params.brand);
  if (params.price_min != null) search.set('price_min', String(params.price_min));
  if (params.price_max != null) search.set('price_max', String(params.price_max));
  if (params.spec) params.spec.forEach((s) => search.append('spec', s));
  if (params.skip) search.set('skip', String(params.skip));
  if (params.limit) search.set('limit', String(params.limit));
  const res = await fetch(`${API_BASE}/components?${search}`);
  if (!res.ok) throw new Error('Не удалось загрузить компоненты');
  return res.json();
}

export async function fetchFacets(category?: string): Promise<FacetsResponse> {
  const search = new URLSearchParams();
  if (category) search.set('category', category);
  const res = await fetch(`${API_BASE}/facets?${search}`);
  if (!res.ok) throw new Error('Не удалось загрузить фильтры');
  return res.json();
}

export async function fetchComponent(id: number): Promise<ComponentDetail> {
  const res = await fetch(`${API_BASE}/components/${id}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Товар не найден');
  }
  return res.json();
}

export async function fetchProductEnrichment(id: number): Promise<ProductEnrichment> {
  const res = await fetch(`${API_BASE}/components/${id}/enrich`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Не удалось обогатить карточку');
  }
  return res.json();
}

export async function fetchCompare(ids: number[]): Promise<{
  category: string | null;
  category_ru: string | null;
  spec_keys: string[];
  components: ComponentDetail[];
}> {
  const res = await fetch(`${API_BASE}/compare?ids=${ids.join(',')}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Ошибка сравнения');
  }
  return res.json();
}

async function readSseStream(
  res: Response,
  onProgress: (ev: ProgressEvent) => void,
): Promise<UpdateResult> {
  if (!res.body) throw new Error('Нет тела ответа (stream)');
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalResult: UpdateResult | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() || '';
    for (const chunk of chunks) {
      const line = chunk
        .split('\n')
        .map((l) => l.trim())
        .find((l) => l.startsWith('data:'));
      if (!line) continue;
      try {
        const data = JSON.parse(line.slice(5).trim()) as ProgressEvent;
        onProgress(data);
        if (data.result) finalResult = data.result;
        if (data.error && !data.result) throw new Error(data.error);
      } catch (e) {
        if (e instanceof SyntaxError) continue;
        throw e;
      }
    }
  }

  if (!finalResult) throw new Error('Операция завершилась без результата');
  return finalResult;
}

export async function updateDatabaseWithProgress(
  options: {
    apiKey?: string;
    economy?: boolean;
    freeOnly?: boolean;
    ymlUrl?: string;
    imageTimeoutSec?: number;
    maxWebImages?: number;
    webImages?: boolean;
    googleApiKey?: string;
    googleCx?: string;
  },
  onProgress: (ev: ProgressEvent) => void,
): Promise<UpdateResult> {
  const res = await fetch(`${API_BASE}/update-database-stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({
      api_key: options.apiKey || undefined,
      economy: !!options.economy,
      free_only: !!options.freeOnly,
      yml_url: options.ymlUrl || undefined,
      image_timeout_sec: options.imageTimeoutSec ?? 15,
      max_web_images: options.maxWebImages ?? 100,
      web_images: options.webImages !== false,
      google_api_key: options.googleApiKey || undefined,
      google_cx: options.googleCx || undefined,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Ошибка обновления');
  }
  return readSseStream(res, onProgress);
}

export async function importCatalogWithProgress(
  items: unknown[],
  onProgress: (ev: ProgressEvent) => void,
): Promise<UpdateResult> {
  const res = await fetch(`${API_BASE}/catalog/import-stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ items }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Ошибка импорта');
  }
  return readSseStream(res, onProgress);
}

export async function exportCatalog(): Promise<{ count: number; items: unknown[] }> {
  const res = await fetch(`${API_BASE}/catalog/export`);
  if (!res.ok) throw new Error('Не удалось экспортировать каталог');
  return res.json();
}

export async function importCatalog(items: unknown[]): Promise<{
  status: string;
  added: number;
  updated: number;
  message: string;
}> {
  const res = await fetch(`${API_BASE}/catalog/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Ошибка импорта');
  }
  return res.json();
}

export function formatPrice(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—';
  return `${Math.round(n).toLocaleString('ru-RU')} ₽`;
}
