// Series colours, in order (same order as the matplotlib plot guidelines).
export const PALETTE = [
  "#185adb",
  "#f9813a",
  "#da0037",
  "#206a5d",
  "#444444",
  "#c4fb6d",
  "#e84a5f",
  "#3edbf0",
  "#ff847c",
  "#ffc947",
] as const;

export const seriesColor = (i: number): string => PALETTE[((i % PALETTE.length) + PALETTE.length) % PALETTE.length];

export const INK = "#111111";
export const GREY = "#6b6b6b";
export const RULE = "#e5e5e5";
export const RULE_STRONG = "#d4d4d4";
export const SIGNAL = "#da0037";
export const PASS = "#206a5d";
export const WARN = "#f9813a";
