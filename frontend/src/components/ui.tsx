import { useEffect, useRef, type ReactNode } from 'react';

/** Угловые метки «чертёжной» рамки из дизайн-системы. */
export function Corners() {
  return (
    <>
      <i className="corner tl" />
      <i className="corner tr" />
      <i className="corner bl" />
      <i className="corner br" />
    </>
  );
}

export function PrimaryButton({ children, onClick, disabled, className = '' }: { children: ReactNode; onClick?: () => void; disabled?: boolean; className?: string }) {
  return (
    <button className={`btn btn-primary btn-xl blueprint ${className}`} onClick={onClick} disabled={disabled}>
      <Corners />
      {children}
    </button>
  );
}

/** Нижняя шторка поверх экрана. Закрывается по фону и Escape, фокус уходит внутрь. */
export function Sheet({ children, onClose, label, modal = true }: { children: ReactNode; onClose?: () => void; label: string; modal?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose?.();
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      prev?.focus?.();
    };
  }, [onClose]);
  const body = (
    <div ref={ref} className="sheet" role="dialog" aria-modal={modal} aria-label={label} tabIndex={-1} onClick={(e) => e.stopPropagation()}>
      {children}
    </div>
  );
  if (!modal) return body;
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      {body}
    </div>
  );
}

export function Toast({ text }: { text: string | null }) {
  return (
    <div className="toast-wrap" aria-live="polite">
      {text && <div className="toast">{text}</div>}
    </div>
  );
}

const svg = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true };

export const Icon = {
  pin: () => (
    <svg {...svg} width={12} height={12}>
      <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  ),
  check: () => (
    <svg {...svg} width={16} height={16} strokeWidth={2}>
      <path d="M20 6 9 17l-5-5" />
    </svg>
  ),
  back: () => (
    <svg {...svg}>
      <path d="m15 18-6-6 6-6" />
    </svg>
  ),
  info: () => (
    <svg {...svg}>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16v-4" />
      <path d="M12 8h.01" />
    </svg>
  ),
  replay: () => (
    <svg {...svg} width={18} height={18}>
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" />
    </svg>
  ),
  flag: () => (
    <svg {...svg} width={16} height={16}>
      <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" />
      <line x1="4" x2="4" y1="22" y2="15" />
    </svg>
  ),
  close: () => (
    <svg {...svg} width={20} height={20}>
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
    </svg>
  ),
};
