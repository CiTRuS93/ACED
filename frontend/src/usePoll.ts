import { useEffect, useState } from "react";

/** Keep previous data on errors, never let an old request update a new selection. */
export function usePoll<T>(
  key: string,
  load: () => Promise<T>,
  interval: number,
) {
  const [state, setState] = useState<{
    key: string;
    data?: T;
    error: string;
    at?: Date;
  }>({ key, error: "" });
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let live = true,
      busy = false;
    const poll = async () => {
      if (busy || document.hidden) return;
      busy = true;
      try {
        const data = await load();
        if (live) setState({ key, data, error: "", at: new Date() });
      } catch (error) {
        if (live)
          setState((old) => ({
            ...(old.key === key ? old : {}),
            key,
            error: String(error instanceof Error ? error.message : error),
          }));
      } finally {
        busy = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), interval);
    const visible = () => {
      if (!document.hidden) void poll();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      live = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
    // key defines the complete identity of the requested resource.
  }, [key, interval, refresh]);
  return {
    ...(state.key === key
      ? state
      : { error: "", data: undefined, at: undefined }),
    refresh: () => setRefresh((x) => x + 1),
  };
}
