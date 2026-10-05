import type { LangPref } from "../i18n";

/**
 * First-run onboarding: what the wizard has done so far, kept in localStorage
 * so a crash, a restart or a quit resumes in place instead of starting over.
 *
 * The shape is versioned; a mismatch simply resets to a clean first run. The
 * wizard writes after every step (and after each choice), so the stored state
 * is always the resume point.
 */

const KEY = "utter.onboarding.v1";
const VERSION = 2;

export type ModelChoice = "recommended" | "minimal" | "skip";

/** The step ids, in order. The shell renders them and the rail reflects them. */
export const ONBOARDING_STEPS = [
  "welcome",
  "language",
  "intro",
  "permissions",
  "keys",
  "apps",
  "models",
  "firstAction",
  "done",
] as const;

export type OnboardingStepId = (typeof ONBOARDING_STEPS)[number];

/** Index of the Models step, used to re-offer the mandatory speech install. */
export const MODELS_STEP_INDEX = ONBOARDING_STEPS.indexOf("models");

export interface OnboardingData {
  /** Index into ONBOARDING_STEPS of the step to resume on. */
  step: number;
  language?: LangPref;
  /** evdev name on Linux, Quartz name on macOS. */
  assistantKey?: string;
  dictationKey?: string;
  /** App ids the user wants Utter to control. */
  apps?: string[];
  /** Set once the app list has loaded and defaults were applied. */
  appsLoaded?: boolean;
  modelChoice?: ModelChoice;
  /** Whether the first run should install the required engine + models. */
  installRuntime?: boolean;
  /**
   * Whether the required whisper.cpp speech model is installed. `false` means
   * the user deferred it on the Models step: setup stays incomplete and the
   * install is offered again on the next run.
   */
  sttInstalled?: boolean;
  /** The user reached the finish screen. */
  tried?: boolean;
}

interface Stored extends OnboardingData {
  version: number;
  updatedAt: number;
}

const EMPTY: OnboardingData = { step: 0 };

function read(): Stored | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Stored;
    if (!parsed || parsed.version !== VERSION) return null;
    return parsed;
  } catch {
    return null;
  }
}

/** Resume data, or a clean first run. Never throws. */
export function loadOnboarding(): OnboardingData {
  const stored = read();
  if (!stored) return { ...EMPTY };
  const raw =
    typeof stored.step === "number" && stored.step >= 0 && stored.step < ONBOARDING_STEPS.length
      ? Math.floor(stored.step)
      : 0;
  // The speech model is required and can't be skipped. If the user deferred it,
  // always resume at the Models step so the install is offered again instead of
  // being silently lost further down the wizard.
  const deferred = stored.sttInstalled === false;
  const step = deferred && raw > MODELS_STEP_INDEX ? MODELS_STEP_INDEX : raw;
  return {
    step,
    language: stored.language,
    assistantKey: stored.assistantKey,
    dictationKey: stored.dictationKey,
    apps: Array.isArray(stored.apps) ? stored.apps.filter((id) => typeof id === "string") : undefined,
    appsLoaded: Boolean(stored.appsLoaded),
    modelChoice: stored.modelChoice,
    installRuntime: typeof stored.installRuntime === "boolean" ? stored.installRuntime : undefined,
    sttInstalled: stored.sttInstalled === true ? true : deferred ? false : undefined,
    tried: Boolean(stored.tried),
  };
}

/** Merge a patch into the stored state. Returns the state as saved. */
export function saveOnboarding(patch: Partial<OnboardingData>): OnboardingData {
  const next = { ...loadOnboarding(), ...patch };
  try {
    localStorage.setItem(
      KEY,
      JSON.stringify({ ...next, version: VERSION, updatedAt: Date.now() } satisfies Stored),
    );
  } catch {
    /* private mode or a full quota: the wizard still works, it just won't resume */
  }
  return next;
}

/**
 * True once the wizard has reached its final step. A deferred speech install
 * keeps it false: the required model still has to be downloaded.
 */
export function isOnboardingComplete(): boolean {
  try {
    const stored = read();
    return Boolean(
      stored && stored.step >= ONBOARDING_STEPS.length - 1 && stored.sttInstalled !== false,
    );
  } catch {
    return false;
  }
}

/**
 * Mark the wizard finished. The record is left in place as the resume point
 * (step = last), so `isOnboardingComplete` is stable across reloads. A deferred
 * speech install (`sttInstalled === false`) is preserved, so the run stays
 * incomplete and is offered again.
 */
export function completeOnboarding(): void {
  saveOnboarding({ step: ONBOARDING_STEPS.length - 1, tried: true });
}

/**
 * Clear the record so the next launch runs the wizard again. Used by
 * "Run setup again" in Settings.
 */
export function resetOnboarding(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

/** A human label for a step, used by the rail's title/aria. */
export function stepIndex(step: OnboardingStepId): number {
  return ONBOARDING_STEPS.indexOf(step);
}
