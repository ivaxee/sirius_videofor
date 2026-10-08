import { useState } from 'react';
import { api, userIdFromToken } from '../api';
import { Icon } from '../components/ui';
import { t } from '../i18n';

const EMAIL = import.meta.env.VITE_CONTACT_EMAIL || 'hello@pokazhdu.example';

export default function About({ consent, onBack, onConsent, onDeleted, toast }: {
  consent: boolean;
  onBack: () => void;
  onConsent: (v: boolean) => Promise<void>;
  onDeleted: () => void;
  toast: (msg: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const uid = userIdFromToken();
  const [before, after] = t('about.contact.text').split('{email}');

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } catch {
      toast(t('error.network'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="screen scroll about">
      <header className="about-top">
        <button className="btn btn-icon btn-ghost" aria-label={t('about.back')} onClick={onBack}>
          <Icon.back />
        </button>
        <span className="about-title">{t('about.title')}</span>
      </header>
      <div className="about-body">
        <section>
          <h4>{t('about.why.title')}</h4>
          <p>{t('about.why.text')}</p>
        </section>
        <section>
          <h4>{t('about.how.title')}</h4>
          <p>{t('about.how.text')}</p>
        </section>
        <section>
          <h4>{t('about.privacy.title')}</h4>
          <div className="list-box">
            <div>{t('about.privacy.1')}</div>
            <div>{t('about.privacy.2')}</div>
            <div>
              {t('about.privacy.3')} <span className="mono">{uid ? `${uid.slice(0, 8)}…` : t('about.privacy.none')}</span>
            </div>
          </div>
        </section>
        <section>
          <h4>{t('about.consent.title')}</h4>
          <p>{consent ? t('about.consent.yes') : t('about.consent.no')}</p>
          <div className="row-gap">
            <button className="btn btn-secondary btn-lg" disabled={busy} onClick={() => run(() => onConsent(!consent))}>
              {consent ? t('about.consent.revoke') : t('about.consent.give')}
            </button>
            {uid && (
              <button
                className="btn btn-ghost btn-lg danger"
                disabled={busy}
                onClick={() =>
                  window.confirm(t('about.deleteConfirm')) &&
                  run(async () => {
                    await api.deleteMe();
                    toast(t('about.deleted'));
                    onDeleted();
                  })
                }
              >
                {t('about.delete')}
              </button>
            )}
          </div>
        </section>
        <section>
          <h4>{t('about.contact.title')}</h4>
          <p>
            {before}
            <a href={`mailto:${EMAIL}`}>{EMAIL}</a>
            {after}
          </p>
        </section>
      </div>
    </main>
  );
}
