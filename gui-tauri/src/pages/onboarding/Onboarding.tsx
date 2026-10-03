import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType } from "react";

import { Titlebar } from "../../components/Titlebar";
import { Button } from "../../components/ui/Button";
import { useI18n } from "../../i18n";
import {
  ONBOARDING_STEPS,
  completeOnboarding,
  loadOnboarding,
  saveOnboarding,
  type OnboardingData,
} from "../../lib/onboarding";
import { ProgressRail } from "./parts";
import {
  AppsStep,
  DoneStep,
  FirstActionStep,
  IntroStep,
  KeysStep,
  LanguageStep,
  ModelsStep,
  PermissionsStep,
  WelcomeStep,
  type NavApi,
  type StepProps,
} from "./steps";

/**
 * The first-run wizard. It replaces the settings shell until it finishes, then
 * calls `onDone`. Progress is written to localStorage after every step, so a
 * crash or quit resumes exactly where it left off (see lib/onboarding.ts).
 *
 * Steps are full screens; the rail and the footer are shared so the visual
 * system stays consistent. Welcome, Models and Done are "bare": they draw
 * their own primary action because they do more than advance (skip, download,
 * finish).
 */

const LAST = ONBOARDING_STEPS.length - 1;
const BARE = new Set([0, 6, LAST]);
const SKIPPABLE = new Set([3, 4, 5, 7]);

const STEPS: ComponentType<StepProps>[] = [
  WelcomeStep,
  LanguageStep,
  IntroStep,
  PermissionsStep,
  KeysStep,
  AppsStep,
  ModelsStep,
  FirstActionStep,
  DoneStep,
];

function clamp(value: number): number {
  return Math.max(0, Math.min(LAST, Math.floor(value)));
}

export function Onboarding({
  onDone,
  initialStep,
}: {
  onDone: () => void;
  /** Dev/screenshot affordance: open straight to one step. */
  initialStep?: number;
}) {
  const { t } = useI18n();
  const [data, setData] = useState<OnboardingData>(() => loadOnboarding());
  const [index, setIndex] = useState<number>(() => clamp(initialStep ?? loadOnboarding().step));
  const [direction, setDirection] = useState<1 | -1>(1);
  const regionRef = useRef<HTMLDivElement>(null);

  const commit = useCallback((patch: Partial<OnboardingData>) => {
    setData(saveOnboarding(patch));
  }, []);

  const goTo = useCallback(
    (next: number) => {
      const target = clamp(next);
      if (target === index) return;
      setDirection(target < index ? -1 : 1);
      commit({ step: target });
      setIndex(target);
    },
    [index, commit],
  );

  const next = useCallback(() => goTo(index + 1), [goTo, index]);
  const back = useCallback(() => goTo(index - 1), [goTo, index]);

  const finish = useCallback(() => {
    completeOnboarding();
    onDone();
  }, [onDone]);

  const skipAll = useCallback(() => {
    completeOnboarding();
    onDone();
  }, [onDone]);

  const nav = useMemo<NavApi>(
    () => ({ index, total: ONBOARDING_STEPS.length, next, back, skip: next, goTo, finish, skipAll }),
    [index, next, back, goTo, finish, skipAll],
  );

  // Move focus to the new step so keyboard and screen-reader users land here.
  useEffect(() => {
    regionRef.current?.scrollTo({ top: 0 });
    regionRef.current?.focus({ preventScroll: true });
  }, [index]);

  // Enter advances, except while typing or when a control already handles it.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Enter" || event.defaultPrevented) return;
      if (BARE.has(index)) return;
      const el = event.target as HTMLElement | null;
      const tag = el?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select" || tag === "button" || tag === "a") return;
      if (el?.isContentEditable) return;
      event.preventDefault();
      next();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, next]);

  const Step = STEPS[index] ?? WelcomeStep;
  const bare = BARE.has(index);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-chrome">
      <Titlebar route="onboarding" onboarding />
      <div className="relative min-h-0 flex-1">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 h-64"
          style={{
            background:
              "radial-gradient(60% 100% at 50% 0%, color-mix(in oklab, var(--primary) 9%, transparent), transparent 70%)",
          }}
        />
        <div className="relative mx-auto flex h-full w-full max-w-[760px] flex-col px-6">
          <ProgressRail index={index} total={ONBOARDING_STEPS.length} onSelect={goTo} />
          <div
            ref={regionRef}
            tabIndex={-1}
            className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-6 outline-none [scrollbar-gutter:stable]"
          >
            <div key={ONBOARDING_STEPS[index]} className={direction === 1 ? "animate-step-in" : "animate-step-back"}>
              <Step data={data} commit={commit} nav={nav} />
            </div>
          </div>

          {!bare && (
            <footer className="flex items-center gap-2 border-t border-line py-3.5">
              <Button variant="ghost" onClick={back} disabled={index === 0}>
                {t("onboarding.back")}
              </Button>
              <div className="ml-auto flex items-center gap-2">
                {SKIPPABLE.has(index) && (
                  <button
                    type="button"
                    onClick={next}
                    className="focus-ring rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
                  >
                    {t("onboarding.skipStep")}
                  </button>
                )}
                <Button variant="primary" iconRight="chevron-right" onClick={next}>
                  {t("onboarding.next")}
                </Button>
              </div>
            </footer>
          )}
        </div>
      </div>
    </div>
  );
}
