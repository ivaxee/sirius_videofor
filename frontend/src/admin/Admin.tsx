import { useCallback, useEffect, useState } from 'react';
import './admin.css';

// Админка: только для команды проекта, поэтому без локализации.
const KEY = 'pz_admin_token';
const LABELS: Record<string, string> = {
  cig: 'Сигарета', vape: 'Вейп', no: 'Не курит', unsure: 'Не уверен', none: '—',
  pending: 'Мало голосов', disputed: 'Расхождение', done: 'Готово',
  active: 'В выдаче', hidden: 'Скрыт', retired: 'Снят',
  scratch: 'Чешется', eat: 'Ест/пьёт', phone: 'Телефон', mask: 'Маска/очки', other: 'Другое',
  too_fast: 'Слишком быстро', burst: 'Пулемёт', same_answer_run: 'Одинаковые подряд',
  inappropriate: 'Неприемлемо', privacy: 'Лицо/номер', broken: 'Не грузится',
};
const label = (k: string) => LABELS[k] ?? k;

type Json = any; // eslint-disable-line @typescript-eslint/no-explicit-any

async function call(path: string, token: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`/api/admin${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...(init?.headers || {}) },
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(String(res.status));
  return res;
}

/** Горизонтальные столбцы одной серии: один цвет, значение подписано текстом. */
function Bars({ data, total, keepOrder }: { data: Record<string, number>; total?: number; keepOrder?: boolean }) {
  const entries = Object.entries(data);
  if (!keepOrder) entries.sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  const sum = total ?? entries.reduce((s, [, v]) => s + v, 0);
  if (!entries.length) return <p className="a-muted">Пока нет данных</p>;
  return (
    <div className="a-bars" role="table">
      {entries.map(([k, v]) => (
        <div key={k} className="a-bar-row" role="row" title={`${label(k)}: ${v} (${sum ? Math.round((v / sum) * 100) : 0}%)`}>
          <span role="cell">{label(k)}</span>
          <span className="a-bar-track" role="cell">
            <span className="a-bar" style={{ width: `${(v / max) * 100}%` }} />
          </span>
          <span className="a-num" role="cell">
            {v.toLocaleString('ru-RU')} <span className="a-muted">{sum ? Math.round((v / sum) * 100) : 0}%</span>
          </span>
        </div>
      ))}
    </div>
  );
}

function Stat({ label: l, value, hint }: { label: string; value: string | number | null | undefined; hint?: string }) {
  return (
    <div className="a-stat">
      <span className="a-muted">{l}</span>
      <span className="a-stat-v">{value ?? '—'}</span>
      {hint && <span className="a-muted a-small">{hint}</span>}
    </div>
  );
}

const kappaHint = (k: number | null | undefined) =>
  k == null ? 'мало данных' : k < 0.2 ? 'слабая' : k < 0.4 ? 'умеренно-слабая' : k < 0.6 ? 'умеренная' : k < 0.8 ? 'хорошая' : 'почти полная';

export default function Admin() {
  const [token, setToken] = useState(() => sessionStorage.getItem(KEY) || '');
  const [input, setInput] = useState('');
  const [tab, setTab] = useState<'summary' | 'agreement' | 'reports' | 'export'>('summary');
  const [loaded, setLoaded] = useState<{ tab: string; data: Json } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exportState, setExportState] = useState('');
  const [minConf, setMinConf] = useState('');

  useEffect(() => {
    document.title = 'Пока жду — админка';
  }, []);

  const load = useCallback(async () => {
    if (!token || tab === 'export') return;
    setError(null);
    try {
      const path = tab === 'summary' ? '/summary' : tab === 'agreement' ? '/agreement' : '/reports';
      setLoaded({ tab, data: await (await call(path, token)).json() });
    } catch (e) {
      if ((e as Error).message === '401') {
        sessionStorage.removeItem(KEY);
        setToken('');
        setError('Неверный токен');
      } else setError('Не удалось загрузить данные');
    }
  }, [token, tab]);

  useEffect(() => {
    load();
  }, [load]);

  if (!token) {
    return (
      <div className="admin">
        <form
          className="a-login"
          onSubmit={(e) => {
            e.preventDefault();
            sessionStorage.setItem(KEY, input);
            setToken(input);
          }}
        >
          <h1>Админка «Пока жду»</h1>
          <label>
            Токен администратора
            <input type="password" value={input} onChange={(e) => setInput(e.target.value)} autoComplete="current-password" />
          </label>
          {error && <p className="a-error">{error}</p>}
          <button className="a-btn a-primary" disabled={!input}>Войти</button>
        </form>
      </div>
    );
  }

  // Данные показываются только для вкладки, под которую загружены.
  const data = loaded?.tab === tab ? loaded.data : null;

  const download = async (format: 'json' | 'csv') => {
    const q = new URLSearchParams({ format });
    if (exportState) q.set('state', exportState);
    if (minConf) q.set('min_confidence', minConf);
    try {
      const res = await call(`/export?${q}`, token);
      const blob = await res.blob();
      const name = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') || '')?.[1] || `labels.${format}`;
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch {
      setError('Экспорт не удался');
    }
  };

  const setStatus = async (id: string, status: string) => {
    await call(`/clips/${id}/status`, token, { method: 'POST', body: JSON.stringify({ status }) });
    load();
  };

  return (
    <div className="admin">
      <header className="a-top">
        <strong>Пока жду · админка</strong>
        <nav>
          {(['summary', 'agreement', 'reports', 'export'] as const).map((t) => (
            <button key={t} className={`a-tab${tab === t ? ' on' : ''}`} onClick={() => setTab(t)}>
              {{ summary: 'Сводка', agreement: 'Согласованность', reports: 'Жалобы', export: 'Экспорт' }[t]}
            </button>
          ))}
        </nav>
        <button
          className="a-btn"
          onClick={() => {
            sessionStorage.removeItem(KEY);
            setToken('');
          }}
        >
          Выйти
        </button>
      </header>
      {error && <p className="a-error">{error}</p>}

      {tab === 'summary' && data && (
        <main className="a-grid">
          <section className="a-card a-wide a-stats">
            <Stat label="Клипов" value={data.clips.total} hint={`из них золотых: ${data.clips.gold}`} />
            <Stat label="Ответов сегодня" value={data.answers.today} />
            <Stat label="Разметчиков" value={data.users.total} hint={`активны сегодня: ${data.users.active_today}`} />
            <Stat label="Точность на золотых" value={data.users.gold_accuracy == null ? null : `${Math.round(data.users.gold_accuracy * 100)}%`} hint={`средний вес ${data.users.avg_weight ?? '—'}`} />
            <Stat label="Заблокировано" value={data.users.blocked} hint="низкая точность" />
            <Stat label="Медиана времени ответа" value={data.answers.median_response_ms ? `${(data.answers.median_response_ms / 1000).toFixed(1)} с` : null} />
            <Stat label="Открытых жалоб" value={data.reports_open} />
          </section>
          <section className="a-card">
            <h2>Итоговые метки (готовые клипы)</h2>
            <Bars data={data.clips.final_labels} />
          </section>
          <section className="a-card">
            <h2>Состояние разметки</h2>
            <Bars data={data.clips.by_state} />
            <p className="a-muted a-small">
              Готово: ≥{data.config.required_votes} голосов и уверенность ≥{data.config.consensus} (или {data.config.max_votes} голосов).
            </p>
          </section>
          <section className="a-card">
            <h2>Все принятые ответы</h2>
            <Bars data={data.answers.by_answer} />
          </section>
          <section className="a-card">
            <h2>Уточнения к «Не курит»</h2>
            <Bars data={data.answers.by_sub_answer} />
          </section>
          <section className="a-card">
            <h2>Отброшено антиспамом</h2>
            <Bars data={data.answers.rejected} />
          </section>
          <section className="a-card">
            <h2>Клипы по статусу</h2>
            <Bars data={data.clips.by_status} />
          </section>
        </main>
      )}

      {tab === 'agreement' && data && (
        <main className="a-grid">
          <section className="a-card a-wide a-stats">
            <Stat label="Cohen's κ (пары разметчиков)" value={data.pairwise_cohen.mean} hint={`${kappaHint(data.pairwise_cohen.mean)} · пар: ${data.pairwise_cohen.pairs}, медиана ${data.pairwise_cohen.median ?? '—'}`} />
            <Stat label="Cohen's κ с итоговой меткой" value={data.vs_consensus_mean} hint={kappaHint(data.vs_consensus_mean)} />
            <Stat label="Fleiss' κ" value={data.fleiss} hint={kappaHint(data.fleiss)} />
            <Stat label="Клипов с ≥2 ответами" value={data.clips_with_2plus} />
          </section>
          <section className="a-card">
            <h2>Точность разметчиков на золотых клипах</h2>
            <Bars data={Object.fromEntries(data.gold_accuracy_hist.map((b: Json) => [`${Math.round(b.from * 100)}–${Math.round(b.to * 100)}%`, b.users]))} keepOrder />
          </section>
          <section className="a-card">
            <h2>Разметчики (анонимно)</h2>
            {data.annotators.length === 0 ? (
              <p className="a-muted">Нужно ≥{data.pairwise_cohen.min_shared} готовых клипов на разметчика</p>
            ) : (
              <table className="a-table">
                <thead>
                  <tr><th>ID</th><th>Клипов</th><th>κ</th><th>Совпадение</th></tr>
                </thead>
                <tbody>
                  {data.annotators.map((a: Json) => (
                    <tr key={a.annotator}>
                      <td className="a-mono">{a.annotator}</td>
                      <td>{a.clips}</td>
                      <td>{a.kappa_vs_consensus ?? '—'}</td>
                      <td>{Math.round(a.agreement * 100)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </main>
      )}

      {tab === 'reports' && data && (
        <main className="a-card a-single">
          <h2>Открытые жалобы</h2>
          {data.length === 0 ? (
            <p className="a-muted">Жалоб нет</p>
          ) : (
            <table className="a-table">
              <thead>
                <tr><th>Клип</th><th>Статус</th><th>Причины</th><th /></tr>
              </thead>
              <tbody>
                {data.map((r: Json) => (
                  <tr key={r.id}>
                    <td className="a-mono">{r.external_id ?? r.id}</td>
                    <td>{label(r.status)}</td>
                    <td>{r.reasons.map(label).join(', ')}</td>
                    <td className="a-actions">
                      <button className="a-btn" onClick={() => setStatus(r.id, 'active')}>Вернуть</button>
                      <button className="a-btn a-danger" onClick={() => setStatus(r.id, 'retired')}>Снять</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </main>
      )}

      {tab === 'export' && (
        <main className="a-card a-single">
          <h2>Экспорт итоговой разметки</h2>
          <p className="a-muted">
            Поля: clip_id, final_label, votes, confidence, label_state, is_gold, score_* (взвешенные голоса), top_no_reason, duration_ms,
            bbox (трек рамки, доли кадра). Перед выгрузкой метки пересчитываются по текущим весам разметчиков.
          </p>
          <div className="a-form">
            <label>
              Состояние
              <select value={exportState} onChange={(e) => setExportState(e.target.value)}>
                <option value="">Все</option>
                <option value="done">Готово</option>
                <option value="disputed">Расхождение</option>
                <option value="pending">Мало голосов</option>
                <option value="gold">Золотые</option>
              </select>
            </label>
            <label>
              Мин. уверенность
              <input type="number" min="0" max="1" step="0.05" value={minConf} onChange={(e) => setMinConf(e.target.value)} placeholder="0–1" />
            </label>
            <button className="a-btn a-primary" onClick={() => download('json')}>Скачать JSON</button>
            <button className="a-btn a-primary" onClick={() => download('csv')}>Скачать CSV</button>
          </div>
        </main>
      )}
    </div>
  );
}
