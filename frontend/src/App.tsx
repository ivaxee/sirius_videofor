import { useCallback, useEffect, useRef, useState } from 'react';
import { api, createSession, flushOutbox, getToken, store, type Batch, type Me } from './api';
import { PrimaryButton, Toast } from './components/ui';
import { t } from './i18n';
import { prefetchClip } from './prefetch';
import About from './screens/About';
import Done from './screens/Done';
import Label, { type InputMode } from './screens/Label';
import { Onboarding1, Onboarding2 } from './screens/Onboarding';

type Screen = 'onb1' | 'onb2' | 'label' | 'empty' | 'done' | 'bye' | 'about';
type EmptyKind = 'limit' | 'exhausted' | 'error';

const STOP_RE = /^[A-Za-z0-9_-]{1,32}$/;
const STOP_TTL_MS = 2 * 60 * 60 * 1000;

/** ?stop= из QR. Запоминаем на 2 часа — для повторного захода с иконки PWA. */
function readStop(): string | null {
  const fromUrl = new URLSearchParams(location.search).get('stop');
  if (fromUrl && STOP_RE.test(fromUrl)) {
    store.set('pz_stop', JSON.stringify({ id: fromUrl, at: Date.now() }));
    return fromUrl;
  }
  try {
    const saved = JSON.parse(store.get('pz_stop') || 'null');
    if (saved && Date.now() - saved.at < STOP_TTL_MS && STOP_RE.test(saved.id)) return saved.id;
  } catch {
    /* ignore */
  }
  return null;
}

const stop = readStop();

export default function App() {
  const onboarded = store.get('pz_onboarded') === '1' && !!getToken();
  const [screen, setScreen] = useState<Screen>(onboarded ? 'label' : 'onb1');
  const [prev, setPrev] = useState<Screen>('label');
  const [consent, setConsent] = useState(store.get('pz_consent') === '1');
  const [busy, setBusy] = useState(false);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [batchNo, setBatchNo] = useState(0);
  const [empty, setEmpty] = useState<EmptyKind>('exhausted');
  const [me, setMe] = useState<Me | null>(null);
  const [prevMe, setPrevMe] = useState<Me | null>(null);
  const [sessionAnswers, setSessionAnswers] = useState(0);
  const [inputMode, setInputMode] = useState<InputMode>(store.get('pz_mode') === 'swipe' ? 'swipe' : 'buttons');
  const [toastText, setToastText] = useState<string | null>(null);
  const toastTimer = useRef<number>();
  const upcoming = useRef<Promise<Batch> | null>(null);
  const loading = useRef(false);

  const toast = useCallback((msg: string) => {
    window.clearTimeout(toastTimer.current);
    setToastText(msg);
    toastTimer.current = window.setTimeout(() => setToastText(null), 2400);
  }, []);

  const applyBatch = useCallback((b: Batch) => {
    setBatchNo((n) => n + 1);
    if (b.clips.length === 0) {
      setBatch(null);
      setEmpty(b.limit_reached ? 'limit' : 'exhausted');
      setScreen((s) => (s === 'label' || s === 'done' ? 'empty' : s));
      return;
    }
    prefetchClip(b.clips[0].url);
    setBatch(b);
  }, []);

  const loadBatch = useCallback(
    async (useUpcoming = false) => {
      const pending = useUpcoming ? upcoming.current : null;
      upcoming.current = null;
      loading.current = true;
      try {
        applyBatch(await (pending ?? api.nextClips(stop)));
      } catch {
        setBatch(null);
        setEmpty('error');
        setScreen((s) => (s === 'label' ? 'empty' : s));
      } finally {
        loading.current = false;
      }
    },
    [applyBatch],
  );

  useEffect(() => {
    flushOutbox();
    const online = () => flushOutbox();
    window.addEventListener('online', online);
    if (onboarded) {
      loadBatch();
      api.me().then((m) => {
        setMe(m);
        setPrevMe(m);
      }).catch(() => undefined);
    }
    return () => window.removeEventListener('online', online);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [screen]);

  const go = (s: Screen) => {
    if (s === 'about') setPrev(screen);
    setScreen(s);
  };

  const start = async () => {
    setBusy(true);
    try {
      if (!getToken()) await createSession();
      store.set('pz_consent', '1');
      setScreen('onb2');
      loadBatch(); // клипы грузятся, пока человек читает пример
    } catch {
      toast(t('error.network'));
    } finally {
      setBusy(false);
    }
  };

  const toClips = () => {
    store.set('pz_onboarded', '1');
    setSessionAnswers(0);
    setPrevMe(me);
    setScreen('label'); // пока пачка грузится — спиннер; пустая выдача сама переключит экран
    if (!batch && !loading.current) loadBatch();
  };

  const finishSession = useCallback(() => {
    setScreen('done');
    upcoming.current = api.nextClips(stop); // следующая пачка — заранее
    upcoming.current.then((b) => b.clips[0] && prefetchClip(b.clips[0].url)).catch(() => undefined);
  }, []);

  const more = async () => {
    setSessionAnswers(0);
    setPrevMe(me);
    setBatch(null);
    setScreen('label');
    await loadBatch(true);
  };

  const onMe = useCallback((m: Me) => {
    setMe(m);
    setSessionAnswers((n) => n + 1);
  }, []);

  const changeConsent = async (v: boolean) => {
    if (v && !getToken()) await createSession();
    else await api.consent(v);
    store.set('pz_consent', v ? '1' : '0');
    setConsent(v);
  };

  let body: JSX.Element;
  switch (screen) {
    case 'onb1':
      body = <Onboarding1 stop={stop} consent={consent} busy={busy} onConsent={setConsent} onStart={start} onAbout={() => go('about')} />;
      break;
    case 'onb2':
      body = <Onboarding2 onBack={() => setScreen('onb1')} onGo={toClips} />;
      break;
    case 'label':
      body = batch ? (
        <Label
          key={batchNo}
          clips={batch.clips}
          stop={stop}
          inputMode={inputMode}
          onInputMode={(m) => {
            setInputMode(m);
            store.set('pz_mode', m);
          }}
          onMe={onMe}
          onFinish={finishSession}
          onAbout={() => go('about')}
          toast={toast}
        />
      ) : (
        <main className="screen pad center">
          <span className="spinner" aria-hidden /> <span className="muted">{t('clip.loading')}</span>
        </main>
      );
      break;
    case 'empty':
      body = (
        <main className="screen pad center-col">
          <h1 className="display">{t(`empty.${empty}.title`)}</h1>
          <p className="lead">{t(`empty.${empty}.text`)}</p>
          {empty === 'error' && (
            <PrimaryButton
              onClick={() => {
                setScreen('label');
                loadBatch();
              }}
            >
              {t('empty.retry')}
            </PrimaryButton>
          )}
          {sessionAnswers > 0 && (
            <button className="btn btn-secondary btn-lg" onClick={() => setScreen('done')}>
              {t('empty.toSummary')}
            </button>
          )}
        </main>
      );
      break;
    case 'done':
      body = <Done me={me} prevMe={prevMe} sessionAnswers={sessionAnswers} stop={stop} onMore={more} onFinish={() => setScreen('bye')} />;
      break;
    case 'bye':
      body = (
        <main className="screen pad center-col">
          <h1 className="display">{t('bye.title')}</h1>
          <p className="lead">{t('bye.text')}</p>
          <button className="btn btn-ghost btn-nav" onClick={more}>
            {t('done.more')}
          </button>
        </main>
      );
      break;
    case 'about':
      body = (
        <About
          consent={consent}
          onBack={() => setScreen(!consent ? 'onb1' : prev === 'about' ? 'label' : prev)}
          onConsent={changeConsent}
          onDeleted={() => {
            setConsent(false);
            setMe(null);
            setBatch(null);
            store.set('pz_onboarded', null);
            setScreen('onb1');
          }}
          toast={toast}
        />
      );
      break;
  }

  return (
    <div className="app">
      {body}
      <Toast text={toastText} />
    </div>
  );
}
