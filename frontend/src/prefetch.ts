// Предзагрузка клипов в Blob: следующий клип скачан, пока человек отвечает на текущий,
// а истечение подписанного URL не мешает показу.

const cache = new Map<string, Promise<string | null>>();

export function prefetchClip(url: string): Promise<string | null> {
  let p = cache.get(url);
  if (!p) {
    p = fetch(url, { mode: 'cors', credentials: 'omit' })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((b) => URL.createObjectURL(b))
      .catch(() => null); // без CORS у хранилища — играем напрямую по URL
    cache.set(url, p);
  }
  return p;
}

export function releaseClip(url: string) {
  const p = cache.get(url);
  if (!p) return;
  cache.delete(url);
  p.then((blobUrl) => blobUrl && setTimeout(() => URL.revokeObjectURL(blobUrl), 2000));
}
