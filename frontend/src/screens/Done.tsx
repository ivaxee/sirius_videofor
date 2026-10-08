import { useEffect, useState } from 'react';
import { api, type Level, type Me, type Stats } from '../api';
import { PrimaryButton, Corners } from '../components/ui';
import { fmt, plural, t, type MessageKey } from '../i18n';
import { StopTag } from './Onboarding';

const LEVELS: Level['key'][] = ['novice', 'observer', 'expert'];
const reduceMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

function useCountUp(target: number, from: number, ms = 900) {
  const [v, setV] = useState(reduceMotion() ? target : from);
  useEffect(() => {
    if (reduceMotion() || target <= from) {
      setV(target);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / ms);
      setV(Math.round(from + (target - from) * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, from, ms]);
  return v;
}

function levelText(level: Level) {
  if (!level.next) return t('level.max');
  const name = t(`level.${level.next.key}` as MessageKey);
  const acc = Math.round(level.next.accuracy_needed * 100);
  if (level.next.answers_needed === 0) return t('level.nextAccuracy', { name, acc });
  return t('level.next', { name, n: level.next.answers_needed, answers: plural('word.answers', level.next.answers_needed), acc });
}

export default function Done({ me, prevMe, sessionAnswers, stop, onMore, onFinish }: {
  me: Me | null;
  prevMe: Me | null;
  sessionAnswers: number;
  stop: string | null;
  onMore: () => void;
  onFinish: () => void;
}) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [animate, setAnimate] = useState(false);

  useEffect(() => {
    api.stats(stop).then(setStats).catch(() => undefined);
    const id = requestAnimationFrame(() => requestAnimationFrame(() => setAnimate(true)));
    return () => cancelAnimationFrame(id);
  }, [stop]);

  const total = stats?.total_answers ?? 0;
  const together = useCountUp(total, Math.max(0, total - sessionAnswers));
  const mine = me?.answers_total ?? 0;
  const level = me?.level;
  const acc = level?.accuracy;
  const startProgress = prevMe && prevMe.level.index === level?.index ? prevMe.level.progress : 0;

  const days = t('week.days').split(',');
  const board = stats?.board.slice(0, 3) ?? [];
  const current = stats?.stop;
  if (current && current.today > 0 && !board.some((b) => b.stop_id === current.stop_id)) board.push(current);

  return (
    <main className="screen pad scroll done-screen">
      <header className="topbar">
        <span className="brand">{t('app.name')}</span>
        <StopTag stop={stop} />
      </header>

      <div className="celebrate" aria-hidden>
        <svg viewBox="0 0 52 52" width="52" height="52">
          <circle cx="26" cy="26" r="24" />
          <path d="M15 27l7 7 15-16" />
        </svg>
      </div>
      <div className="kicker">{t('done.kicker')}</div>
      <h1 className="display">{t('done.title', { n: fmt.format(mine), clips: plural('word.clips', mine) })}</h1>
      <p className="lead">
        {t('done.together')} <b className="count">{stats ? fmt.format(together) : '…'}</b>
      </p>

      {level && (
        <section className="blueprint level-card">
          <Corners />
          <div className="level-head">
            <span className="level-name">{t(`level.${level.key}` as MessageKey)}</span>
            <span className="muted small">
              {acc === null || acc === undefined ? t('done.accuracyUnknown') : t('done.accuracy', { p: Math.round(acc * 100) })}
            </span>
          </div>
          <div className="level-steps">
            {LEVELS.map((key, i) => {
              let fill = 0;
              if (i <= level.index) fill = 100;
              else if (i === level.index + 1) fill = Math.round((animate ? level.progress : startProgress) * 100);
              return (
                <div key={key}>
                  <div className="level-track">
                    <div className="level-fill" style={{ width: `${fill}%` }} />
                  </div>
                  <span className="muted tiny">{t(`level.${key}` as MessageKey)}</span>
                </div>
              );
            })}
          </div>
          <p className="small">{levelText(level)}</p>
        </section>
      )}

      <div className="stat-grid">
        <div>
          <span className="muted small">{t('streak.label')}</span>
          <span className="stat-value">{t('streak.value', { n: me?.streak ?? 0, days: plural('word.days', me?.streak ?? 0) })}</span>
          <div className="week">
            {days.map((d, i) => (
              <div key={d} className={me?.week[i] ? 'on' : ''}>
                <i />
                <span>{d}</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <span className="muted small">{t('stopToday.label')}</span>
          {current ? (
            <>
              <span className="stat-value">{t('stopToday.value', { n: fmt.format(current.today), clips: plural('word.clips', current.today) })}</span>
              <span className="small">
                {t(current.region ? 'stopToday.rankRegion' : 'stopToday.rank', {
                  rank: current.rank,
                  of: current.of,
                  stops: plural('word.stopsOf', current.of),
                })}
              </span>
            </>
          ) : (
            <span className="small">{t('stopToday.noStop')}</span>
          )}
        </div>
      </div>

      <section className="board">
        <div className="section-kicker">{t('board.title')}</div>
        {stats && board.length === 0 && <p className="small muted">{t('board.empty')}</p>}
        {board.map((r) => {
          const me_ = current?.stop_id === r.stop_id;
          return (
            <div key={r.stop_id} className={`board-row${me_ ? ' me' : ''}`}>
              <span className="rank">{r.rank}</span>
              <span>
                {r.name}
                {me_ && <span className="muted"> — {t('board.you')}</span>}
              </span>
              <span className="n">{fmt.format(r.today)}</span>
            </div>
          );
        })}
      </section>

      <div className="grow" />
      <PrimaryButton onClick={onMore}>{t('done.more')}</PrimaryButton>
      <button className="btn btn-secondary btn-lg" onClick={onFinish}>
        {t('done.finish')}
      </button>
    </main>
  );
}
