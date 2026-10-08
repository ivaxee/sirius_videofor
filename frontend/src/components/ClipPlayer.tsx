import { useEffect, useRef, useState } from 'react';
import type { BoxKey } from '../api';
import { prefetchClip } from '../prefetch';
import { t } from '../i18n';

export function boxAt(track: BoxKey[], time: number): BoxKey {
  if (track.length === 1 || time <= track[0].t) return track[0];
  for (let i = 1; i < track.length; i++) {
    const b = track[i];
    if (time <= b.t) {
      const a = track[i - 1];
      const p = (time - a.t) / (b.t - a.t || 1);
      return { t: time, x: a.x + (b.x - a.x) * p, y: a.y + (b.y - a.y) * p, w: a.w + (b.w - a.w) * p, h: a.h + (b.h - a.h) * p };
    }
  }
  return track[track.length - 1];
}

interface Props {
  url: string;
  durationMs: number;
  width: number | null;
  height: number | null;
  bbox: BoxKey[];
  replayToken?: number;
  label?: string;
  dim?: boolean;
  paused?: boolean;
  onFirstFrame?: () => void;
  onError?: () => void;
}

type Status = 'loading' | 'playing' | 'blocked' | 'error';

export default function ClipPlayer({ url, durationMs, width, height, bbox, replayToken, label, dim = true, paused, onFirstFrame, onError }: Props) {
  const video = useRef<HTMLVideoElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>('loading');
  const [attempt, setAttempt] = useState(0);
  const firstFrame = useRef(false);

  // Источник: Blob из предзагрузки, иначе прямой подписанный URL.
  useEffect(() => {
    let alive = true;
    setStatus('loading');
    setSrc(null);
    firstFrame.current = false;
    const fallback = setTimeout(() => alive && setSrc((s) => s ?? url), 6000);
    prefetchClip(url).then((blob) => alive && setSrc(blob ?? url));
    return () => {
      alive = false;
      clearTimeout(fallback);
    };
  }, [url, attempt]);

  useEffect(() => {
    const v = video.current;
    if (!v || !src) return;
    v.muted = true;
    v.defaultMuted = true;
    v.play().catch(() => setStatus((s) => (s === 'loading' ? 'blocked' : s)));
  }, [src]);

  useEffect(() => {
    const v = video.current;
    if (!v || replayToken === undefined || replayToken === 0) return;
    v.currentTime = 0;
    v.play().catch(() => undefined);
  }, [replayToken]);

  useEffect(() => {
    const v = video.current;
    if (!v || !src) return;
    if (paused) v.pause();
    else if (status === 'playing') v.play().catch(() => undefined);
  }, [paused, src, status]);

  // Рамка и прогресс обновляются напрямую в DOM на каждом кадре — без перерисовки React.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const v = video.current;
      if (v && box.current) {
        const time = v.currentTime || 0;
        const b = boxAt(bbox, time);
        const s = box.current.style;
        s.left = `${b.x * 100}%`;
        s.top = `${b.y * 100}%`;
        s.width = `${b.w * 100}%`;
        s.height = `${b.h * 100}%`;
        if (bar.current) bar.current.style.width = `${Math.min(100, (time / (v.duration || durationMs / 1000)) * 100)}%`;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [bbox, durationMs]);

  const ratio = width && height ? `${width} / ${height}` : '4 / 3';

  return (
    <div className="clip" style={{ aspectRatio: ratio }}>
      <video
        key={attempt}
        ref={video}
        src={src ?? undefined}
        muted
        playsInline
        autoPlay
        loop
        preload="auto"
        disablePictureInPicture
        controls={false}
        aria-label={label}
        onPlaying={() => {
          setStatus('playing');
          if (!firstFrame.current) {
            firstFrame.current = true;
            onFirstFrame?.();
          }
        }}
        onError={() => {
          if (src && src !== url && src.startsWith('blob:')) {
            setSrc(url); // повреждённый Blob — пробуем напрямую
            return;
          }
          setStatus('error');
          onError?.();
        }}
      />
      <span className="clip-meta">{t('clip.meta', { dur: (durationMs / 1000).toFixed(1) })}</span>
      <div ref={box} className={`clip-box${dim ? ' dim' : ''}`}>
        <span>{t('clip.inFrame')}</span>
      </div>
      <div ref={bar} className="clip-progress" />
      {status === 'loading' && (
        <div className="clip-overlay" aria-live="polite">
          <span className="spinner" aria-hidden /> {t('clip.loading')}
        </div>
      )}
      {status === 'blocked' && (
        <button
          className="clip-overlay clip-play"
          onClick={() => {
            video.current?.play().then(() => setStatus('playing')).catch(() => undefined);
          }}
        >
          ▶ {t('clip.tapToPlay')}
        </button>
      )}
      {status === 'error' && (
        <div className="clip-overlay">
          <span>{t('clip.error')}</span>
          <button className="btn btn-secondary on-dark" onClick={() => setAttempt((a) => a + 1)}>
            {t('clip.retry')}
          </button>
        </div>
      )}
    </div>
  );
}
