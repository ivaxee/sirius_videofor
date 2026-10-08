import ru, { type MessageKey, type Messages, type Plural } from './ru';
import en from './en';

export type { MessageKey };

// Чтобы добавить язык: создайте src/i18n/<код>.ts по образцу en.ts и впишите его сюда.
const LOCALES: Record<string, Partial<Messages>> = { ru, en };
export type Locale = 'ru' | 'en';

function detect(): Locale {
  const fromUrl = new URLSearchParams(location.search).get('lang');
  let saved: string | null = null;
  try {
    saved = localStorage.getItem('pz_lang');
  } catch {
    /* приватный режим */
  }
  // Русский по умолчанию; другой язык — только явно через ?lang=xx (запоминается).
  const candidates = [fromUrl, saved];
  for (const c of candidates) {
    const code = c?.slice(0, 2).toLowerCase();
    if (code && code in LOCALES) {
      if (c === fromUrl) {
        try {
          localStorage.setItem('pz_lang', code);
        } catch {
          /* ignore */
        }
      }
      return code as Locale;
    }
  }
  return 'ru';
}

export const locale: Locale = detect();
document.documentElement.lang = locale;
const dict = LOCALES[locale];
const rules = new Intl.PluralRules(locale);

function raw(key: MessageKey): string | Plural {
  return dict[key] ?? ru[key];
}

export function t(key: MessageKey, vars?: Record<string, string | number>): string {
  const msg = raw(key);
  const s = typeof msg === 'string' ? msg : msg.other;
  return vars ? s.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`)) : s;
}

/** Форма слова для числа: plural('word.clips', 5) → «клипов». */
export function plural(key: MessageKey, n: number): string {
  const msg = raw(key);
  if (typeof msg === 'string') return msg;
  const form = rules.select(n) as keyof Plural;
  return msg[form] ?? msg.other;
}

export const fmt = new Intl.NumberFormat(locale);
