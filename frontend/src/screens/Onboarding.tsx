import ClipPlayer from '../components/ClipPlayer';
import { Icon, PrimaryButton } from '../components/ui';
import { t } from '../i18n';
import example from '../example-clip.json';

export function StopTag({ stop }: { stop: string | null }) {
  if (!stop) return null;
  return (
    <span className="tag tag-accent tag-icon">
      <Icon.pin />
      {t('stop.tag', { id: stop })}
    </span>
  );
}

function Steps({ n }: { n: 1 | 2 }) {
  return (
    <div className="steps" aria-hidden>
      <div className="on" />
      <div className={n === 2 ? 'on' : ''} />
    </div>
  );
}

export function Onboarding1({ stop, consent, busy, onConsent, onStart, onAbout }: {
  stop: string | null;
  consent: boolean;
  busy: boolean;
  onConsent: (v: boolean) => void;
  onStart: () => void;
  onAbout: () => void;
}) {
  return (
    <main className="screen pad">
      <header className="topbar">
        <span className="brand">{t('app.name')}</span>
        <StopTag stop={stop} />
      </header>
      <Steps n={1} />
      <div className="kicker">{t('onb1.kicker')}</div>
      <h1 className="display">{t('onb1.title')}</h1>
      <p className="lead">{t('onb1.text')}</p>
      <div className="facts">
        {([1, 2, 3] as const).map((i) => (
          <div key={i}>
            <span className="fact-value">{t(`onb1.fact${i}.value`)}</span>
            <span className="fact-label">{t(`onb1.fact${i}.label`)}</span>
          </div>
        ))}
      </div>
      <div className="grow" />
      <label className="consent">
        <input type="checkbox" checked={consent} onChange={(e) => onConsent(e.target.checked)} />
        <span className="box" aria-hidden>{consent && <Icon.check />}</span>
        <span>
          {t('onb1.consent')}{' '}
          <a
            href="#about"
            onClick={(e) => {
              e.preventDefault();
              onAbout();
            }}
          >
            {t('onb1.more')}
          </a>
        </span>
      </label>
      <PrimaryButton disabled={!consent || busy} onClick={onStart}>
        {t('onb1.start')}
      </PrimaryButton>
    </main>
  );
}

export function Onboarding2({ onBack, onGo }: { onBack: () => void; onGo: () => void }) {
  return (
    <main className="screen pad">
      <header className="topbar">
        <button className="btn btn-ghost btn-nav" onClick={onBack}>
          <Icon.back />
          {t('onb2.back')}
        </button>
        <button className="btn btn-ghost btn-nav" onClick={onGo}>
          {t('onb2.skip')}
        </button>
      </header>
      <Steps n={2} />
      <h2 className="title">{t('onb2.title')}</h2>
      <ClipPlayer
        url="/example.mp4"
        durationMs={example.duration_ms}
        width={example.width}
        height={example.height}
        bbox={example.bbox}
        dim={false}
        label={t('onb2.exampleTag')}
      />
      <div className="example-answer">
        <div>
          <span className="muted small">{t('onb2.correct')}</span>
          <span className="example-label">{t('onb2.answer')}</span>
        </div>
        <span className="tag tag-accent">{t('onb2.hint')}</span>
      </div>
      <ol className="rules">
        <li>{t('onb2.rule1')}</li>
        <li>{t('onb2.rule2')}</li>
        <li>{t('onb2.rule3')}</li>
      </ol>
      <div className="grow" />
      <PrimaryButton onClick={onGo}>{t('onb2.go')}</PrimaryButton>
    </main>
  );
}
