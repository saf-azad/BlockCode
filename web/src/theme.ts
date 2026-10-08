// Colours from the v4 design. Every language has its own palette; the whole editor re-themes
// when the language changes, and the blocks keep their place.
import type { Lang } from './types';

export interface Theme {
  c0: string;
  c1: string;
  c2: string;
  acc: string;
}

export const THEMES: Record<Lang, Theme> = {
  sql: { c0: '#FFF5F5', c1: '#FDE8E8', c2: '#FAD0D0', acc: '#ED7070' },
  python: { c0: '#F5F6FF', c1: '#E6E9FD', c2: '#D0D6FA', acc: '#7D8DF0' },
  r: { c0: '#F4FBF5', c1: '#E3F4E6', c2: '#C9EACF', acc: '#62BE74' },
};

type Swatch = { bg: string; code: string };

// One shade per clause, darkest at the top of the stack (From) to lightest (Limit).
export const PAL: Record<Lang, Record<string, Swatch>> = {
  sql: {
    from: { bg: '#E04A4F', code: '#7A1414' },
    join: { bg: '#E8605F', code: '#A51E22' },
    derive: { bg: '#EB6B6A', code: '#AE2226' },
    where: { bg: '#EE7676', code: '#B8262B' },
    group: { bg: '#F28C8C', code: '#B73A38' },
    having: { bg: '#F6A3A6', code: '#A8403F' },
    select: { bg: '#F8B0B3', code: '#A84249' },
    order: { bg: '#F9BCBF', code: '#A8444F' },
    limit: { bg: '#FCD6D9', code: '#9E4452' },
  },
  python: {
    from: { bg: '#6A7FEE', code: '#1E2A6B' },
    join: { bg: '#7D8DF0', code: '#2F45A8' },
    derive: { bg: '#8691F0', code: '#3A4CB4' },
    where: { bg: '#8F95F1', code: '#3F52BE' },
    group: { bg: '#A29DF2', code: '#4A4FC0' },
    having: { bg: '#B5AAF5', code: '#5A44B8' },
    select: { bg: '#BEB2F6', code: '#6244B4' },
    order: { bg: '#C8BAF7', code: '#6A44B0' },
    limit: { bg: '#DCCDF9', code: '#6B48A8' },
  },
  r: {
    from: { bg: '#4CB363', code: '#1E6B33' },
    join: { bg: '#62BE74', code: '#23753A' },
    derive: { bg: '#6DC37D', code: '#27793D' },
    where: { bg: '#78C886', code: '#2A7D40' },
    group: { bg: '#8FD199', code: '#2F7F45' },
    having: { bg: '#A6DBAD', code: '#357F4A' },
    select: { bg: '#B2E0B8', code: '#387E4C' },
    order: { bg: '#BDE5C2', code: '#3A7D4E' },
    limit: { bg: '#D4EFD7', code: '#3E7A52' },
  },
};

export const INK = '#111111';
export const ERROR = '#C42828';

export function applyTheme(lang: Lang): void {
  const t = THEMES[lang];
  const root = document.documentElement;
  root.style.setProperty('--c0', t.c0);
  root.style.setProperty('--c1', t.c1);
  root.style.setProperty('--c2', t.c2);
  root.style.setProperty('--acc', t.acc);
  root.style.setProperty('--kw', PAL[lang].from.code);
  root.dataset.lang = lang;
}

export function blockColour(lang: Lang, type: string): Swatch | null {
  return PAL[lang][type] ?? null;
}
