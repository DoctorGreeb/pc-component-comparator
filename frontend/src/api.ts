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
  min_price: number | null;
  in_stock: boolean;
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

export async function fetchCategories(): Promise<Category[]> {
  const res = await fetch(`${API_BASE}/categories`);
  if (!res.ok) throw new Error('Failed to load categories');
  return res.json();
}

export async function fetchComponents(params: {
  category?: string;
  q?: string;
  skip?: number;
  limit?: number;
}): Promise<ComponentListItem[]> {
  const search = new URLSearchParams();
  if (params.category) search.set('category', params.category);
  if (params.q) search.set('q', params.q);
  if (params.skip) search.set('skip', String(params.skip));
  if (params.limit) search.set('limit', String(params.limit));
  const res = await fetch(`${API_BASE}/components?${search}`);
  if (!res.ok) throw new Error('Failed to load components');
  return res.json();
}

export async function fetchCompare(ids: number[]): Promise<{
  category: string | null;
  category_ru: string | null;
  components: ComponentDetail[];
}> {
  const res = await fetch(`${API_BASE}/compare?ids=${ids.join(',')}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to compare');
  }
  return res.json();
}

export async function updateDatabase(apiKey?: string): Promise<{
  status: string;
  message: string;
  note?: string;
  components_added: number;
  categories_ready: number;
}> {
  const res = await fetch(`${API_BASE}/update-database`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(apiKey ? { api_key: apiKey } : {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Update failed');
  }
  return res.json();
}
