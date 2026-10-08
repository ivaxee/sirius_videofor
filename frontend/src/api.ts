import { locale } from './i18n';

export type AnswerKey = 'cig' | 'vape' | 'no' | 'unsure';
export type SubKey = 'scratch' | 'eat' | 'phone' | 'mask' | 'other';
export type ReportReason = 'inappropriate' | 'privacy' | 'broken' | 'other';

export interface BoxKey { t: number; x: number; y: number; w: number; h: number }

export interface Clip {
  assignment_id: string;
  url: string;
  duration_ms: number;
  width: number | null;
  height: number | null;
  bbox: BoxKey[];
}

export interface Batch { clips: Clip[]; limit_reached: boolean; exhausted: boolean }

export interface Level {
  key: 'novice' | 'observer' | 'expert';
  index: number;
  next: null | { key: Level['key']; answers_needed: number; accuracy_needed: number; gold_needed: number };
  progress: number;
  accuracy: number | null;
}

export interface Me {
  user_id: string;
  consent: boolean;
  answers_total: number;
  gold_total: number;
  gold_correct: number;
  level: Level;
  streak: number;
  week: boolean[];
  paused: boolean;
}

export interface AnswerResult {
  accepted: boolean;
  reason: string | null;
  gold?: { match: boolean | null; expert_answer: AnswerKey; explanation: string };
  me: Me;
}

export interface BoardRow { stop_id: string; name: string; today: number; rank: number }
export interface Stats {
  total_answers: number;
  stop: (BoardRow & { of: number; region: string | null }) | null;
  board: BoardRow[];
}

// --- локальное хранилище (всё в try: приватный режим Safari может бросать) -----

export const store = {
  get(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key: string, value: string | null) {
    try {
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch {
      /* ignore */
    }
  },
};

const TOKEN = 'pz_token';
const OUTBOX = 'pz_outbox';

export const getToken = () => store.get(TOKEN);
export const userIdFromToken = () => getToken()?.split('.')[0] ?? null;

export class HttpError extends Error {
  constructor(public status: number, public code: string) {
    super(code);
  }
}

async function request<T>(method: string, path: string, body?: unknown, timeoutMs = 10000, retryAuth = true): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  try {
    const res = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctrl.signal,
      cache: 'no-store',
      credentials: 'omit',
    });
    if (res.status === 401 && retryAuth && store.get('pz_consent') === '1' && path !== '/session') {
      // Токен потерян/устарел: молча создаём новую анонимную сессию.
      await createSession();
      return request<T>(method, path, body, timeoutMs, false);
    }
    if (!res.ok) {
      let code = String(res.status);
      try {
        code = (await res.json()).detail ?? code;
      } catch {
        /* not json */
      }
      throw new HttpError(res.status, code);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export async function createSession(): Promise<void> {
  const r = await request<{ token: string }>('POST', '/session', { consent: true, locale }, 10000, false);
  store.set(TOKEN, r.token);
  store.set('pz_consent', '1');
}

export const api = {
  nextClips: (stop: string | null, n = 3) =>
    request<Batch>('GET', `/next-clips?n=${n}${stop ? `&stop=${encodeURIComponent(stop)}` : ''}`),
  answer: (body: { assignment_id: string; answer: AnswerKey; sub_answer: SubKey | null; response_time_ms: number }) =>
    request<AnswerResult>('POST', '/answers', { ...body, locale }, 8000),
  report: (assignment_id: string, reason: ReportReason) => request<{ ok: boolean }>('POST', '/reports', { assignment_id, reason }),
  stats: (stop: string | null) => request<Stats>('GET', `/stats${stop ? `?stop=${encodeURIComponent(stop)}` : ''}`),
  me: () => request<Me>('GET', '/me'),
  consent: (consent: boolean) => request<Me>('POST', '/me/consent', { consent }),
  deleteMe: async () => {
    await request<{ ok: boolean }>('DELETE', '/me', undefined, 10000, false);
    store.set(TOKEN, null);
    store.set('pz_consent', null);
    store.set(OUTBOX, null);
  },
};

// --- офлайн-очередь ответов --------------------------------------------------

type Pending = Parameters<typeof api.answer>[0];

function readOutbox(): Pending[] {
  try {
    return JSON.parse(store.get(OUTBOX) || '[]');
  } catch {
    return [];
  }
}

export function queueAnswer(a: Pending) {
  const box = readOutbox().filter((x) => x.assignment_id !== a.assignment_id);
  box.push(a);
  store.set(OUTBOX, JSON.stringify(box.slice(-50)));
}

let flushing = false;
export async function flushOutbox(): Promise<void> {
  if (flushing || !navigator.onLine) return;
  flushing = true;
  try {
    for (const item of readOutbox()) {
      try {
        await api.answer(item);
      } catch (e) {
        // Сетевая ошибка — попробуем позже; ответ сервера 4xx — отбрасываем.
        if (!(e instanceof HttpError) || e.status >= 500 || e.status === 429) break;
      }
      store.set(OUTBOX, JSON.stringify(readOutbox().filter((x) => x.assignment_id !== item.assignment_id)));
      await new Promise((r) => setTimeout(r, 400)); // сервер отбрасывает «пулемётные» ответы
    }
  } finally {
    flushing = false;
  }
}

export function isNetworkError(e: unknown) {
  return !(e instanceof HttpError) || e.status >= 500;
}
