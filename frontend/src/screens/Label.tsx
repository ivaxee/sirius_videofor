import { useCallback, useEffect, useRef, useState } from 'react';
import { api, isNetworkError, queueAnswer, type AnswerKey, type Clip, type Me, type ReportReason, type SubKey } from '../api';
import ClipPlayer from '../components/ClipPlayer';
import { Icon, PrimaryButton, Sheet } from '../components/ui';
import { t, type MessageKey } from '../i18n';
import { prefetchClip, releaseClip } from '../prefetch';

export const MIN_RESPONSE_MS = 1000; // совпадает с серверным MIN_RESPONSE_MS
const SUB_TIMEOUT_MS = 6000;
const SWIPE_THRESHOLD = 90;
const ANSWERS: AnswerKey[] = ['cig', 'vape', 'no', 'unsure'];
const SUBS: SubKey[] = ['scratch', 'eat', 'phone', 'mask', 'other'];
const REASONS: ReportReason[] = ['inappropriate', 'privacy', 'broken', 'other'];
const TIPS = [1, 2, 3, 4, 5, 6] as const;

export type InputMode = 'buttons' | 'swipe';
type SheetKind = null | 'sub' | 'feedback' | 'help' | 'report';
interface Feedback { match: boolean | null; mine: AnswerKey; expert: AnswerKey; why: string }

interface Props {
  clips: Clip[];
  stop: string | null;
  inputMode: InputMode;
  onInputMode: (m: InputMode) => void;
  onMe: (me: Me) => void;
  onFinish: () => void;
  onAbout: () => void;
  toast: (msg: string) => void;
}

function swipeAnswer(dx: number, dy: number, threshold: number): AnswerKey | null {
  if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > threshold) return dx > 0 ? 'cig' : 'no';
  if (Math.abs(dy) > threshold) return dy < 0 ? 'vape' : 'unsure';
  return null;
}

export default function Label({ clips, stop, inputMode, onInputMode, onMe, onFinish, onAbout, toast }: Props) {
  const [idx, setIdx] = useState(0);
  const [sheet, setSheet] = useState<SheetKind>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [reason, setReason] = useState<ReportReason | null>(null);
  const [busy, setBusy] = useState(false);
  const [replay, setReplay] = useState(0);
  const [dragLabel, setDragLabel] = useState<AnswerKey | null>(null);
  const clip = clips[idx];

  const shownAt = useRef<number | null>(null); // первый кадр клипа на экране
  const mountedAt = useRef(performance.now());
  const failed = useRef(false);
  const rt = useRef(0);
  const subTimer = useRef<number>();
  const drag = useRef<{ x: number; y: number; id: number } | null>(null);
  const card = useRef<HTMLDivElement>(null);

  useEffect(() => {
    shownAt.current = null;
    failed.current = false;
    mountedAt.current = performance.now();
    if (clips[idx + 1]) prefetchClip(clips[idx + 1].url);
  }, [idx, clips]);

  useEffect(() => () => window.clearTimeout(subTimer.current), []);

  const next = useCallback(() => {
    releaseClip(clip.url);
    setFeedback(null);
    setSheet(null);
    setReplay(0);
    if (idx + 1 >= clips.length) onFinish();
    else setIdx(idx + 1);
  }, [clip, idx, clips.length, onFinish]);

  const commit = useCallback(
    async (answer: AnswerKey, sub: SubKey | null) => {
      window.clearTimeout(subTimer.current);
      setSheet(null);
      const payload = { assignment_id: clip.assignment_id, answer, sub_answer: sub, response_time_ms: rt.current };
      setBusy(true);
      try {
        const res = await api.answer(payload);
        onMe(res.me);
        if (res.gold) {
          setFeedback({ match: res.gold.match, mine: answer, expert: res.gold.expert_answer, why: res.gold.explanation });
          setSheet('feedback');
          return;
        }
      } catch (e) {
        if (isNetworkError(e)) {
          queueAnswer(payload); // слабая сеть: не теряем ответ и не задерживаем человека
          toast(t('label.offline'));
        }
      } finally {
        setBusy(false);
      }
      next();
    },
    [clip, next, onMe, toast],
  );

  const answer = useCallback(
    (key: AnswerKey) => {
      if (sheet || busy) return;
      const start = shownAt.current ?? (failed.current ? mountedAt.current : null);
      const elapsed = start === null ? 0 : Math.round(performance.now() - start);
      if (elapsed < MIN_RESPONSE_MS) {
        toast(t('label.tooFast'));
        return;
      }
      rt.current = elapsed;
      if (key === 'no') {
        setSheet('sub');
        subTimer.current = window.setTimeout(() => commit('no', null), SUB_TIMEOUT_MS);
      } else commit(key, null);
    },
    [sheet, busy, commit, toast],
  );

  // Клавиши 1–4 — для разметки с компьютера.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (sheet || e.target instanceof HTMLInputElement) return;
      const i = Number(e.key) - 1;
      if (i >= 0 && i < ANSWERS.length) answer(ANSWERS[i]);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [answer, sheet]);

  const sendReport = async () => {
    if (!reason) return;
    setSheet(null);
    try {
      await api.report(clip.assignment_id, reason);
    } catch {
      /* клип всё равно скрываем у себя */
    }
    toast(t('report.thanks'));
    next();
  };

  // --- свайпы: двигаем карточку напрямую через style, без перерисовки на каждый пиксель
  const setCard = (dx: number, dy: number, animate: boolean) => {
    const s = card.current?.style;
    if (!s) return;
    s.transition = animate ? 'transform .25s ease' : 'none';
    s.transform = dx || dy ? `translate(${dx}px, ${dy}px) rotate(${dx / 25}deg)` : '';
  };
  const swipe = inputMode === 'swipe' && !sheet;
  const pointer = swipe
    ? {
        onPointerDown: (e: React.PointerEvent) => {
          drag.current = { x: e.clientX, y: e.clientY, id: e.pointerId };
          (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
        },
        onPointerMove: (e: React.PointerEvent) => {
          if (!drag.current) return;
          const dx = e.clientX - drag.current.x;
          const dy = e.clientY - drag.current.y;
          setCard(dx, dy, false);
          setDragLabel(swipeAnswer(dx, dy, 40));
        },
        onPointerUp: (e: React.PointerEvent) => {
          if (!drag.current) return;
          const k = swipeAnswer(e.clientX - drag.current.x, e.clientY - drag.current.y, SWIPE_THRESHOLD);
          drag.current = null;
          setCard(0, 0, true);
          setDragLabel(null);
          if (k) answer(k);
        },
        onPointerCancel: () => {
          drag.current = null;
          setCard(0, 0, true);
          setDragLabel(null);
        },
      }
    : {};

  const paused = sheet === 'help' || sheet === 'report' || sheet === 'feedback';

  return (
    <main className="screen label-screen">
      <header className="label-top">
        <button className="btn btn-icon btn-ghost" aria-label={t('label.about')} onClick={onAbout}>
          <Icon.info />
        </button>
        <div className="label-progress">
          <div className="label-progress-text">
            <span>{t('label.progress', { n: idx + 1, total: clips.length })}</span>
            {stop && <span>№{stop}</span>}
          </div>
          <div className="bars" aria-hidden>
            {clips.map((c, i) => (
              <div key={c.assignment_id} className={i < idx ? 'done' : i === idx ? 'now' : ''} />
            ))}
          </div>
        </div>
        <button className="btn btn-icon btn-secondary help-btn" aria-label={t('label.help')} onClick={() => setSheet('help')}>
          ?
        </button>
      </header>

      <div ref={card} className={`clip-card${swipe ? ' swipeable' : ''}`} {...pointer}>
        <ClipPlayer
          key={clip.assignment_id}
          url={clip.url}
          durationMs={clip.duration_ms}
          width={clip.width}
          height={clip.height}
          bbox={clip.bbox}
          replayToken={replay}
          paused={paused}
          label={t('label.question')}
          onFirstFrame={() => {
            shownAt.current = performance.now();
          }}
          onError={() => {
            failed.current = true;
          }}
        />
        {dragLabel && (
          <div className="drag-label">
            <span>{t(`drag.${dragLabel}` as MessageKey)}</span>
          </div>
        )}
      </div>

      <div className="clip-actions">
        <button className="btn btn-ghost btn-nav" onClick={() => setReplay((r) => r + 1)}>
          <Icon.replay />
          {t('label.replay')}
        </button>
        <button
          className="btn btn-ghost btn-nav muted"
          onClick={() => {
            setReason(null);
            setSheet('report');
          }}
        >
          <Icon.flag />
          {t('label.report')}
        </button>
      </div>

      <h2 className="question">{t('label.question')}</h2>
      <div className="grow" />

      {inputMode === 'buttons' ? (
        <div className="answers" aria-busy={busy}>
          {ANSWERS.map((k) => (
            <button key={k} className={`btn btn-secondary answer answer-${k}`} disabled={busy} onClick={() => answer(k)}>
              {t(`answer.${k}`)}
            </button>
          ))}
        </div>
      ) : (
        <div className="swipe-pad" aria-busy={busy}>
          <span />
          <button className="btn btn-secondary" disabled={busy} onClick={() => answer('vape')}>{t('swipe.vape')}</button>
          <span />
          <button className="btn btn-secondary" disabled={busy} onClick={() => answer('no')}>{t('swipe.no')}</button>
          <div className="swipe-hint">{t('swipe.hint')}</div>
          <button className="btn btn-secondary" disabled={busy} onClick={() => answer('cig')}>{t('swipe.cig')}</button>
          <span />
          <button className="btn btn-secondary" disabled={busy} onClick={() => answer('unsure')}>{t('swipe.unsure')}</button>
          <span />
        </div>
      )}

      {sheet === 'sub' && (
        <Sheet label={t('sub.title')} modal={false}>
          <div className="sheet-head">
            <span className="sheet-title">{t('sub.title')}</span>
            <span className="muted small">{t('sub.optional')}</span>
          </div>
          <div className="sub-grid">
            {SUBS.map((s) => (
              <button key={s} className="btn btn-secondary" onClick={() => commit('no', s)}>
                {t(`sub.${s}`)}
              </button>
            ))}
          </div>
          <button className="btn btn-ghost skip" onClick={() => commit('no', null)}>
            {t('sub.skip')}
            <span className="countdown" style={{ animationDuration: `${SUB_TIMEOUT_MS}ms` }} />
          </button>
        </Sheet>
      )}

      {sheet === 'feedback' && feedback && (
        <Sheet label={t('gold.kicker')} modal={false}>
          <span className="card-kicker">{t('gold.kicker')}</span>
          <span className="feedback-title">
            {feedback.match === null ? t('gold.unsure') : feedback.match ? t('gold.match') : t('gold.miss')}
          </span>
          <div className="feedback-grid">
            <span className="muted">{t('gold.you')}</span>
            <span>{t(`answer.${feedback.mine}`)}</span>
            <span className="muted">{t('gold.expert')}</span>
            <span className="strong">{t(`answer.${feedback.expert}`)}</span>
          </div>
          {feedback.why && <p className="feedback-why">{feedback.why}</p>}
          <PrimaryButton onClick={next}>{t('gold.next')}</PrimaryButton>
        </Sheet>
      )}

      {sheet === 'help' && (
        <Sheet label={t('help.title')} onClose={() => setSheet(null)}>
          <div className="sheet-head">
            <span className="sheet-title">{t('help.title')}</span>
            <button className="btn btn-icon btn-ghost" aria-label={t('help.close')} onClick={() => setSheet(null)}>
              <Icon.close />
            </button>
          </div>
          <div className="tips">
            {TIPS.map((i) => (
              <div key={i} className="tip">
                <span className="tip-q">{t(`tip${i}.q`)}</span>
                <span className="tip-a">
                  <span className="tag tag-accent">{t(`tip${i}.a`)}</span> {t(`tip${i}.why`)}
                </span>
              </div>
            ))}
          </div>
          <div className="mode-row">
            <span className="muted">{t('help.mode')}</span>
            <div className="seg" role="radiogroup" aria-label={t('help.mode')}>
              {(['buttons', 'swipe'] as const).map((m) => (
                <label key={m} className="seg-opt">
                  <input type="radio" name="mode" checked={inputMode === m} onChange={() => onInputMode(m)} />
                  {t(`help.mode.${m}`)}
                </label>
              ))}
            </div>
          </div>
        </Sheet>
      )}

      {sheet === 'report' && (
        <Sheet label={t('report.title')} onClose={() => setSheet(null)}>
          <span className="sheet-title">{t('report.title')}</span>
          <p className="sheet-text">{t('report.text')}</p>
          <div className="reasons" role="radiogroup">
            {REASONS.map((r) => (
              <label key={r} className="radio">
                <input type="radio" name="reason" checked={reason === r} onChange={() => setReason(r)} />
                <span className="dot" />
                {t(`report.${r}`)}
              </label>
            ))}
          </div>
          <div className="sheet-actions">
            <button className="btn btn-secondary" onClick={() => setSheet(null)}>
              {t('report.cancel')}
            </button>
            <button className="btn btn-primary" disabled={!reason} onClick={sendReport}>
              {t('report.send')}
            </button>
          </div>
        </Sheet>
      )}
    </main>
  );
}
