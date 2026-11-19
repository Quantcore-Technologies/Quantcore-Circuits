import { useLayoutEffect, useState } from "react";

/**
 * Width of an element in CSS px, kept up to date with a ResizeObserver.
 * Returns a callback ref, so it also works when the element only mounts after data arrives.
 */
export function useElementWidth<T extends HTMLElement>(fallback = 600) {
  const [el, setEl] = useState<T | null>(null);
  const [width, setWidth] = useState(fallback);

  useLayoutEffect(() => {
    if (!el) return;
    const update = () => setWidth(Math.floor(el.getBoundingClientRect().width) || fallback);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [el, fallback]);

  return [setEl, width] as const;
}
