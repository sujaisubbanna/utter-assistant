import { useCallback, useEffect, useRef, useState } from "react";

import { Sidebar } from "./components/Sidebar";
import { Titlebar } from "./components/Titlebar";
import { ToastProvider } from "./components/ui/Toast";
import { I18nProvider, useT } from "./i18n";
import { api } from "./lib/api";
import { ConfigProvider, useConfig } from "./lib/config";
import { navLabelKey } from "./lib/nav";
import { RunnerStatusProvider } from "./lib/status";
import { ThemeProvider } from "./lib/theme";
import { isPageId, PAGES } from "./pages";

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
  const { loading: configLoading } = useConfig();
  useSplash(!configLoading);
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
        <main
          ref={mainRef}
          className="mb-2 mr-2 min-h-0 flex-1 overflow-y-auto rounded-xl bg-panel shadow-panel"
        >
          <div key={route} className="animate-fade-up">
            <Page />
          </div>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <I18nProvider>
        <ToastProvider>
          <ConfigProvider>
            <RunnerStatusProvider>
              <Shell />
            </RunnerStatusProvider>
          </ConfigProvider>
        </ToastProvider>
      </I18nProvider>
    </ThemeProvider>
  );
}
