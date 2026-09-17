import { useCallback, useEffect, useRef, useState } from 'react';

// Простейший кэш на сессию: возврат на таб не перезапрашивает данные (ТЗ 10 — не лагает).
const cache = new Map<string, unknown>();

export function cached<T>(key: string): T | undefined {
  return cache.get(key) as T | undefined;
}

export function putCache<T>(key: string, value: T) {
  cache.set(key, value);
}

export function dropCache(prefix: string) {
  for (const key of [...cache.keys()]) {
    if (key.startsWith(prefix)) cache.delete(key);
  }
}

export interface Resource<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  reload: () => void;
  set: (value: T) => void;
}

export function useResource<T>(key: string, loader: () => Promise<T>): Resource<T> {
  const [data, setData] = useState<T | undefined>(() => cached<T>(key));
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!cached<T>(key));
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let alive = true;
    const hit = cached<T>(key);
    if (hit !== undefined && tick === 0) {
      setData(hit);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    loaderRef
      .current()
      .then((value) => {
        if (!alive) return;
        putCache(key, value);
        setData(value);
        setLoading(false);
      })
      .catch(() => {
        if (!alive) return;
        setError('load');
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [key, tick]);

  const reload = useCallback(() => {
    cache.delete(key);
    setTick((t) => t + 1);
  }, [key]);

  const set = useCallback(
    (value: T) => {
      putCache(key, value);
      setData(value);
    },
    [key],
  );

  return { data, error, loading, reload, set };
}
