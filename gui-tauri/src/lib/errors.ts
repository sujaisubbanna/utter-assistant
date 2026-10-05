import { useCallback } from "react";

import type { MessageKey, Vars } from "../i18n";
import { useI18n } from "../i18n";

type Translate = (key: MessageKey, vars?: Vars) => string;

/**
 * The shapes a spawn failure takes when its program is missing — most often the
 * Python interpreter, which is empty until the engine is installed. None of
 * these are useful to a person, so they all collapse to one friendly message.
 */
const ENGINE_MISSING =
  /engine_missing|os error 2\b|no such file or directory|failed to spawn/i;

function errorText(error: unknown): string {
  if (error == null) return "";
  if (typeof error === "string") return error;
  return String((error as Error)?.message ?? error);
}

/** True when `error` is (or contains) a missing-engine spawn failure. */
export function isEngineMissing(error: unknown): boolean {
  return ENGINE_MISSING.test(errorText(error));
}

/**
 * Turn any thrown value / command error into something a person can read.
 *
 * A missing engine becomes "the engine isn't installed" instead of the raw
 * Rust/OS string (`No such file or directory (os error 2)`); everything else is
 * passed through, with an empty value falling back to a generic message.
 */
export function humanizeError(error: unknown, t: Translate): string {
  const text = errorText(error).trim();
  if (isEngineMissing(text)) return t("engine.missing.short");
  return text || t("common.somethingWrong");
}

/** `humanizeError` bound to the current language. */
export function useHumanizeError(): (error: unknown) => string {
  const { t } = useI18n();
  return useCallback((error: unknown) => humanizeError(error, t), [t]);
}
