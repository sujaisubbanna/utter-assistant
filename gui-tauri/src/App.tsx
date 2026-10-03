import { useCallback, useEffect, useRef, useState } from "react";

import { Sidebar } from "./components/Sidebar";
import { Titlebar } from "./components/Titlebar";
import { ToastProvider } from "./components/ui/Toast";
import { I18nProvider, useT } from "./i18n";
import { api } from "./lib/api";
import { ConfigProvider, useConfig } from "./lib/config";
import { navLabelKey } from "./lib/nav";
import { isOnboardingComplete } from "./lib/onboarding";
import { PlatformProvider, usePlatform } from "./lib/platform";
import { RunnerStatusProvider } from "./lib/status";
import { ThemeProvider } from "./lib/theme";
import { Onboarding } from "./pages/onboarding/Onboarding";
import { isPageId, PAGES } from "./pages";
import { LINUX_AGENT_UNITS, markSetupSeen, setupSeen } from "./pages/Setup";

function routeFromHash(): string {
  const id = window.location.hash.replace(/^#\/?/, "");
  return isPageId(id) ? id : "general";
}

// The build-in settles at ~1.4 s; hold it so the promise line can be read.
const SPLASH_MIN_MS = 2800;

/** Fade the pre-React splash out once settings are in (and it has had its moment). */
function useSplash(ready: boolean) {
  useEffect(() => {
    if (!ready) return;
    const node = document.getElementById("splash");
    if (!node) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const wait = reduced ? 0 : Math.max(0, SPLASH_MIN_MS - performance.now());
    const hide = window.setTimeout(() => node.classList.add("out"), wait);
    const remove = window.setTimeout(() => node.remove(), wait + (reduced ? 0 : 420));
    return () => {
      window.clearTimeout(hide);
      window.clearTimeout(remove);
    };
  }, [ready]);
}

function Shell() {
  const t = useT();
  const { isMac, ready: platformReady } = usePlatform();
  const [route, setRoute] = useState<string>(routeFromHash);
  const [version, setVersion] = useState("0.1.0");
  const mainRef = useRef<HTMLElement>(null);

  const navigate = useCallback((id: string) => {
    if (!isPageId(id)) return;
    setRoute(id);
    if (window.location.hash !== `#/${id}`) window.location.hash = `/${id}`;
  }, []);

  useEffect(() => {
    api
      .appInfo()
      .then((info) => setVersion(info.version))
      .catch(() => {});
    api
      .bootParams()
      .then((boot) => {
        // Dev/screenshot affordance: UTTER_GUI_ROUTE forces the first page.
        const [id, query] = String(boot.route ?? "").split("?");
        if (import.meta.env.DEV && query) sessionStorage.setItem("utter.dev.query", query);
        if (id && isPageId(id)) navigate(id);
      })
      .catch(() => {});
  }, [navigate]);

  // Open Set up on launch whenever the assistant is not usable:
  //  - any platform, first run: the seen flag is not set yet;
  //  - macOS: the flag is set but a required privacy permission is still
  //    missing (the flag persists across reinstalls, so a fresh install with
  //    no grants would otherwise land on General);
  //  - Linux: the flag is set but the runner user unit is not active.
  // The service check runs once per launch and only while the default route is
  // showing, so it never yanks the user back after they navigate away.
  useEffect(() => {
    if (!platformReady) return;
    // Respect an explicit route (deep link / dev override).
    if (window.location.hash && routeFromHash() !== "general") return;
    const goSetup = () => {
      if (routeFromHash() === "general") navigate("setup");
    };
    if (!setupSeen()) {
      goSetup();
      return;
    }
    let cancelled = false;
    if (isMac) {
      api
        .macosPermissions()
        .then((report) => {
          if (!cancelled && report && !report.all_granted) goSetup();
        })
        .catch(() => {});
    } else {
      api
        .systemctlShow(LINUX_AGENT_UNITS)
        .then((statuses) => {
          if (cancelled) return;
          const runner = statuses.find((status) => status.id === "utter-runner") ?? statuses[0];
          if (runner?.active_state !== "active") goSetup();
        })
        .catch(() => {});
    }
    return () => {
      cancelled = true;
    };
  }, [platformReady, isMac, navigate]);

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    document.title = `${t("app.name")} — ${t(navLabelKey(route))}`;
    mainRef.current?.scrollTo({ top: 0 });
  }, [route, t]);

  const Page = PAGES[route] ?? PAGES.general;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-chrome">
      <Titlebar route={route} />
      <div className="flex min-h-0 flex-1">
        <Sidebar active={route} onNavigate={navigate} version={version} />
        {/* Shadow and rounding live on this non-scrolling wrapper. Putting
            shadow-panel on the scroller itself repainted the whole panel every
            frame, which is what made scrolling feel laggy under WebKitGTK. */}
        <div className="mb-2 mr-2 flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-panel shadow-panel">
          <main
            ref={mainRef}
            className="min-h-0 flex-1 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]"
          >
            <div key={route} className="animate-fade-up">
              <Page />
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}

/**
 * Decides whether the first-run wizard or the settings shell is shown. The
 * wizard gates the app until it is finished; a page route in `UTTER_GUI_ROUTE`
 * still wins in a dev build so screenshots can reach any page.
 */
function Root() {
  const { loading: configLoading } = useConfig();
  const { ready: platformReady } = usePlatform();
  const [onboardingDone, setOnboardingDone] = useState<boolean>(() => isOnboardingComplete());
  const [forcedStep, setForcedStep] = useState<number | null | undefined>(undefined);
  const [bypass, setBypass] = useState(false);

  // Keep the pre-React splash until we know which screen to paint.
  useSplash(!configLoading && platformReady && forcedStep !== undefined);

  useEffect(() => {
    // Dev/screenshot affordance: `?onboarding=<step>` opens straight to a step.
    const params = new URLSearchParams(window.location.search);
    if (import.meta.env.DEV && params.has("onboarding")) {
      const step = Number(params.get("onboarding"));
      setForcedStep(Number.isFinite(step) ? Math.max(0, step) : 0);
      return;
    }
    api
      .bootParams()
      .then((boot) => {
        const [id, query] = String(boot.route ?? "").split("?");
        if (id === "onboarding") {
          const step = Number(new URLSearchParams(query ?? "").get("step"));
          setForcedStep(Number.isFinite(step) ? Math.max(0, step) : 0);
          return;
        }
        if (import.meta.env.DEV && id && isPageId(id) && id !== "general") {
          setBypass(true);
        }
        setForcedStep(null);
      })
      .catch(() => setForcedStep(null));
  }, []);

  const done = useCallback(() => {
    // Let the shell's own "open Set up when unusable" logic take over from here.
    markSetupSeen();
    setOnboardingDone(true);
    setForcedStep(null);
    setBypass(false);
  }, []);

  if (forcedStep === undefined || !platformReady) return null;

  if (forcedStep !== null || (!onboardingDone && !bypass)) {
    return <Onboarding initialStep={forcedStep ?? undefined} onDone={done} />;
  }
  return <Shell />;
}

export default function App() {
  return (
    <ThemeProvider>
      <I18nProvider>
        <ToastProvider>
          <PlatformProvider>
            <ConfigProvider>
              <RunnerStatusProvider>
                <Root />
              </RunnerStatusProvider>
            </ConfigProvider>
          </PlatformProvider>
        </ToastProvider>
      </I18nProvider>
    </ThemeProvider>
  );
}
