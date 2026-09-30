import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api } from "../lib/api";
import { en, type Messages } from "./en";
import { es } from "./es";

/**
 * Tiny, dependency-free i18n.
 *
 * - `en` is the source of truth; every other locale is typed against it, so a
 *   missing or misspelt key is a compile error.
 * - `t("a.b.c", { name })` interpolates `{name}`.
 * - `tn("a.b", count)` picks `one` / `other` via `Intl.PluralRules` and
 *   exposes `{count}`.
 * - The choice is a per-window UI preference (localStorage), like the theme —
 *   it is never written to config.toml.
 */

export const LOCALES = { en, es } as const;
export type Lang = keyof typeof LOCALES;
export type LangPref = Lang | "system";
export const LANGS: Lang[] = ["en", "es"];

/** Native names, so a user can always find their own language. */
export const LANG_NAMES: Record<Lang, string> = { en: "English", es: "Español" };

const STORAGE_KEY = "utter.lang";

type Leaves<T, P extends string = ""> = {
  [K in keyof T & string]: T[K] extends string
    ? `${P}${K}`
    : T[K] extends { one: string; other: string }
      ? `${P}${K}`
      : Leaves<T[K], `${P}${K}.`>;
}[keyof T & string];

type PluralKeys<T, P extends string = ""> = {
  [K in keyof T & string]: T[K] extends { one: string; other: string }
    ? `${P}${K}`
    : T[K] extends string
      ? never
      : PluralKeys<T[K], `${P}${K}.`>;
}[keyof T & string];

export type MessageKey = Leaves<Messages>;
export type PluralKey = PluralKeys<Messages>;
export type Vars = Record<string, string | number>;

function lookup(tree: unknown, key: string): unknown {
  let node: unknown = tree;
  for (const part of key.split(".")) {
    if (node && typeof node === "object" && part in (node as object)) {
      node = (node as Record<string, unknown>)[part];
    } else {
      return undefined;
    }
  }
  return node;
}

function interpolate(text: string, vars?: Vars): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}

export function detectLang(): Lang {
  const candidates = navigator.languages?.length ? navigator.languages : [navigator.language];
  for (const tag of candidates) {
    const base = String(tag || "").toLowerCase().split("-")[0] as Lang;
    if (LANGS.includes(base)) return base;
  }
  return "en";
}

function storedPref(): LangPref {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "system" || LANGS.includes(raw as Lang)) return raw as LangPref;
  } catch {
    /* ignore */
  }
  return "system";
}

export function translate(lang: Lang, key: string, vars?: Vars): string {
  const value = lookup(LOCALES[lang], key) ?? lookup(en, key);
  if (typeof value !== "string") {
    if (import.meta.env.DEV) console.warn(`[i18n] missing key: ${key}`);
    return key;
  }
  return interpolate(value, vars);
}

interface I18nValue {
  lang: Lang;
  pref: LangPref;
  setPref: (pref: LangPref) => void;
  t: (key: MessageKey, vars?: Vars) => string;
  tn: (key: PluralKey, count: number, vars?: Vars) => string;
  /** Locale-aware number formatting. */
  num: (value: number, options?: Intl.NumberFormatOptions) => string;
}

function makeValue(lang: Lang, pref: LangPref, setPref: (pref: LangPref) => void): I18nValue {
  const rules = new Intl.PluralRules(lang);
  const t = (key: MessageKey, vars?: Vars) => translate(lang, key, vars);
  const tn = (key: PluralKey, count: number, vars?: Vars) =>
    translate(lang, `${key}.${rules.select(count) === "one" ? "one" : "other"}`, { count, ...vars });
  const num = (value: number, options?: Intl.NumberFormatOptions) =>
    new Intl.NumberFormat(lang, options).format(value);
  return { lang, pref, setPref, t, tn, num };
}

// English fallback so a consumer outside the provider (or mid hot-reload) still renders.
const I18nContext = createContext<I18nValue>(makeValue("en", "system", () => {}));

export function I18nProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<LangPref>(storedPref);
  const lang: Lang = pref === "system" ? detectLang() : pref;

  useEffect(() => {
    // Dev/screenshot affordance: UTTER_GUI_LANG forces the first language.
    api
      .bootParams()
      .then((boot) => {
        const forced = String(boot.lang ?? "").toLowerCase() as Lang;
        if (LANGS.includes(forced)) setPrefState(forced);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setPref = useCallback((next: LangPref) => {
    setPrefState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo(() => makeValue(lang, pref, setPref), [lang, pref, setPref]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  return useContext(I18nContext);
}

/** Shorthand for components that only need `t`. */
export function useT() {
  return useI18n().t;
}
