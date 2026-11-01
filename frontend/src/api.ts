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

export async function updateDatabase(
  apiKey?: string,
  economy = false,
): Promise<{
  status: string;
  message: string;
  note?: string;
  components_added: number;
  categories_ready: number;
  economy?: boolean;
  credits_exhausted?: boolean;
}> {
  const res = await fetch(`${API_BASE}/update-database`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey || undefined, economy }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Ошибка обновления');
  }
  return res.json();
}

/** Бесплатная подгрузка без ReefAPI-ключа */
export async function updateDatabaseFree(ymlUrl?: string): Promise<{
  status: string;
  message: string;
  note?: string;
  components_added: number;
  categories_ready: number;
}> {
  const res = await fetch(`${API_BASE}/update-database-free`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ free_only: true, yml_url: ymlUrl || undefined }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Ошибка бесплатной загрузки');
  }
  return res.json();
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
