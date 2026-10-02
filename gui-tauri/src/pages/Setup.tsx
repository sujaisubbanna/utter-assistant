import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Icon, type IconName } from "../components/icons";
import { PageBody, PageHeader, PageNote } from "../components/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Row, Tile, Value } from "../components/ui/Row";
import { SkeletonRows } from "../components/ui/Skeleton";
import { StatusDot, type DotTone } from "../components/ui/StatusDot";
import { useToast } from "../components/ui/Toast";
import { useI18n, type MessageKey } from "../i18n";
import { api } from "../lib/api";
import { useConfig } from "../lib/config";
import { useTauriEvent } from "../lib/events";
import { usePoll } from "../lib/hooks";
import { displayMacKey } from "../lib/keys";
import { usePlatform } from "../lib/platform";
import type { AppInfo, InstallStatus, PermissionItem, PermissionReport, UnitStatus } from "../lib/types";

/**
 * macOS onboarding, in the spirit of Raycast's first run: one screen that
 * walks the privacy permissions the assistant needs, says why each one is
 * needed, opens the exact System Settings pane, and re-checks live until
 * everything is granted. The checks run in the daemon's own python so the
 * result (and the prompt) belongs to the binary launchd runs.
 */

const PANE: Record<string, string> = {
  microphone: "Privacy_Microphone",
  speech_recognition: "Privacy_SpeechRecognition",
  input_monitoring: "Privacy_ListenEvent",
  accessibility: "Privacy_Accessibility",
  screen_recording: "Privacy_ScreenCapture",
};

const ICON: Record<string, IconName> = {
  microphone: "mic",
  speech_recognition: "wave",
  input_monitoring: "keyboard",
  accessibility: "hand",
  screen_recording: "monitor",
};

const LABEL_KEY: Record<string, MessageKey> = {
  microphone: "setup.permissions.microphone",
  speech_recognition: "setup.permissions.speech",
  input_monitoring: "setup.permissions.inputMonitoring",
  accessibility: "setup.permissions.accessibility",
  screen_recording: "setup.permissions.screenRecording",
};

const WHY_KEY: Record<string, MessageKey> = {
  microphone: "setup.permissions.microphoneWhy",
  speech_recognition: "setup.permissions.speechWhy",
  input_monitoring: "setup.permissions.inputMonitoringWhy",
  accessibility: "setup.permissions.accessibilityWhy",
  screen_recording: "setup.permissions.screenRecordingWhy",
};

/** Prompt-able permissions: macOS shows a dialog for these on request. */
const PROMPTS = new Set(["microphone", "speech_recognition", "input_monitoring", "accessibility", "screen_recording"]);

/** Grants that only take effect for newly started processes, so the launchd
 *  agents must be restarted when either flips to granted. */
const RESTART_ON_GRANT = ["input_monitoring", "accessibility"];

// macOS runs two launchd agents. On Linux the installer only installs the
// runner user unit (`install/utter-runner.service`); the old utter-bridge and
// friends are legacy units the installer removes, so they are not shown.
const MAC_AGENT_UNITS = ["utter-runner", "utter-bridge"];
export const LINUX_AGENT_UNITS = ["utter-runner"];
const SETUP_SEEN = "utter.setup.seen";

export function markSetupSeen(): void {
  try {
    localStorage.setItem(SETUP_SEEN, "1");
  } catch {
    /* ignore */
  }
}

export function setupSeen(): boolean {
  try {
    return localStorage.getItem(SETUP_SEEN) === "1";
  } catch {
    return false;
  }
}

function statusMeta(status: string): { tone: DotTone; key: MessageKey; badge: "ok" | "warn" | "danger" | "muted" } {
  switch (status) {
    case "granted":
      return { tone: "ok", key: "setup.status.granted", badge: "ok" };
    case "denied":
      return { tone: "error", key: "setup.status.denied", badge: "danger" };
    case "not_determined":
      return { tone: "warn", key: "setup.status.notAsked", badge: "warn" };
    default:
      return { tone: "unknown", key: "setup.status.unknown", badge: "muted" };
  }
}

function PermissionRow({
  item,
  onRequest,
  busy,
}: {
  item: PermissionItem;
  onRequest: (id: string) => void;
  busy: boolean;
}) {
  const { t } = useI18n();
  const meta = statusMeta(item.status);
  const granted = item.status === "granted";
  return (
    <Row
      leading={<Tile icon={ICON[item.id] ?? "shield"} tone={granted ? "ok" : item.status === "denied" ? "danger" : "muted"} />}
      title={
        <span className="flex items-center gap-2">
          {t(LABEL_KEY[item.id] ?? "setup.permissions.other")}
          <Badge tone={meta.badge} dot>
            {t(meta.key)}
          </Badge>
        </span>
      }
      description={t(WHY_KEY[item.id] ?? "setup.permissions.otherWhy")}
    >
      {!granted && PROMPTS.has(item.id) && (
        <Button size="sm" variant="primary" loading={busy} onClick={() => onRequest(item.id)}>
          {t("setup.actions.grant")}
        </Button>
      )}
      <Button
        size="sm"
        variant={granted ? "ghost" : "secondary"}
        icon="external"
        onClick={() => void api.openSettingsPane(PANE[item.id] ?? "Privacy").catch(() => {})}
      >
        {t("setup.actions.openSettings")}
      </Button>
    </Row>
  );
}

function AgentRow({ unit, status, onStart, busy }: { unit: string; status?: UnitStatus; onStart: () => void; busy: boolean }) {
  const { t } = useI18n();
  const { isMac } = usePlatform();
  const installed = status && status.load_state !== "not-found" && Boolean(status.load_state);
  const running = status?.active_state === "active";
  const tone: DotTone = !status ? "unknown" : running ? "ok" : installed ? "muted" : "warn";
  const label = unit === "utter-runner" ? t("setup.agent.runner") : t("setup.agent.assistant");
  return (
    <Row
      leading={<Tile icon={unit === "utter-runner" ? "cpu" : "mic"} tone={running ? "ok" : "muted"} />}
      title={label}
      description={
        !status
          ? t("general.services.checking")
          : running
            ? t("setup.agent.running")
            : installed
              ? t("setup.agent.stopped")
              : isMac
                ? t("setup.agent.notInstalled")
                : t("general.services.notInstalled")
      }
    >
      <StatusDot tone={tone} pulse={running} />
      {installed && !running && (
        <Button size="sm" variant="primary" icon="play" loading={busy} onClick={onStart}>
          {t("general.hero.start")}
        </Button>
      )}
    </Row>
  );
}

function RuntimeRow({
  install,
  installing,
  progress,
  error,
  onInstall,
}: {
  install: InstallStatus | null;
  installing: boolean;
  progress: string | null;
  error: string | null;
  onInstall: () => void;
}) {
  const { t } = useI18n();
  if (!install) {
    return <Row leading={<Tile icon="box" />} title={t("setup.runtime.title")} description={t("general.services.checking")} />;
  }
  const version = install.installed_version ?? "";
  let tone: "ok" | "warn" | "muted" | "danger" = "muted";
  let description: string;
  if (installing) {
    description = progress ?? t("setup.runtime.installing");
    tone = "warn";
  } else if (error) {
    description = t("setup.runtime.failed", { error });
    tone = "danger";
  } else if (install.installed && install.update_available) {
    description = t("setup.runtime.updateAvailable", { current: version, next: install.bundled_version ?? "" });
    tone = "warn";
  } else if (install.installed) {
    description = t("setup.runtime.installed", { version, dir: install.runtime_dir });
    tone = "ok";
  } else if (install.bundled) {
    description = t("setup.runtime.notInstalled");
    tone = "warn";
  } else {
    description = t("setup.runtime.notBundled", { repo: install.repo });
  }
  const label = install.installed
    ? install.update_available
      ? t("setup.runtime.update")
      : t("setup.runtime.reinstall")
    : t("setup.runtime.install");
  return (
    <Row leading={<Tile icon="box" tone={tone} />} title={t("setup.runtime.title")} description={description}>
      {install.installed && !installing && <Badge tone="ok" dot>{t("setup.status.installed")}</Badge>}
      {install.bundled && (
        <Button
          size="sm"
          variant={install.installed && !install.update_available ? "secondary" : "primary"}
          icon="download"
          loading={installing}
          onClick={onInstall}
        >
          {label}
        </Button>
      )}
    </Row>
  );
}

export function SetupPage() {
  const { t } = useI18n();
  const toast = useToast();
  const { isMac, ready } = usePlatform();
  const { get, reload: reloadConfig } = useConfig();
  const [install, setInstall] = useState<InstallStatus | null>(null);
  const [installing, setInstalling] = useState(false);
  const [installError, setInstallError] = useState<string | null>(null);
  const [installProgress, setInstallProgress] = useState<string | null>(null);
  const autoInstalled = useRef(false);
  const [report, setReport] = useState<PermissionReport | null>(null);
  // Granted ids from the previous report; `null` until the first one, so an
  // already-granted permission on load is never mistaken for a transition.
  const grantedRef = useRef<Set<string> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requesting, setRequesting] = useState<string | null>(null);
  const [agents, setAgents] = useState<Record<string, UnitStatus>>({});
  const [starting, setStarting] = useState<string | null>(null);
  const [info, setInfo] = useState<AppInfo | null>(null);
  const units = isMac ? MAC_AGENT_UNITS : LINUX_AGENT_UNITS;

  useEffect(() => {
    markSetupSeen();
  }, []);

  useEffect(() => {
    api.appInfo().then(setInfo).catch(() => {});
  }, []);

  useTauriEvent<{ stage: string; message: string }>(
    "setup://progress",
    (payload) => setInstallProgress(payload.message),
    installing,
  );

  const runInstall = useCallback(async () => {
    setInstalling(true);
    setInstallError(null);
    setInstallProgress(null);
    try {
      const next = await api.macosInstall();
      setInstall(next);
      await reloadConfig();
      toast(t("setup.runtime.done"), "ok");
    } catch (err) {
      setInstallError(String(err));
    } finally {
      setInstalling(false);
    }
  }, [reloadConfig, toast, t]);

  // Drag-and-drop install: the first visit unpacks the bundled runtime on its own.
  useEffect(() => {
    if (!isMac) return;
    api
      .macosInstallStatus()
      .then((status) => {
        setInstall(status);
        if (status.bundled && (!status.installed || status.update_available) && !autoInstalled.current) {
          autoInstalled.current = true;
          void runInstall();
        } else if (status.installed && !status.agents_installed && !autoInstalled.current) {
          // Agents from an older build (or none): rewrite them to launch through this app.
          autoInstalled.current = true;
          void api.macosReinstallAgents().then(setInstall).catch((err) => setInstallError(String(err)));
        }
      })
      .catch((err) => setInstallError(String(err)));
  }, [isMac, runInstall]);

  const refresh = useCallback(async () => {
    if (isMac) {
      try {
        const next = await api.macosPermissions();
        if (next && Array.isArray(next.permissions)) {
          const nowGranted = new Set(
            next.permissions.filter((item) => item.status === "granted").map((item) => item.id),
          );
          const previous = grantedRef.current;
          grantedRef.current = nowGranted;
          // Restart once on a false→true transition (never on the first report):
          // Input Monitoring / Accessibility only apply to newly started processes.
          if (previous && RESTART_ON_GRANT.some((id) => nowGranted.has(id) && !previous.has(id))) {
            void api
              .macosRestartAgents()
              .then(() => toast(t("plugins.restarted"), "ok"))
              .catch((err) => console.warn("utter: restarting agents after grant failed", err));
          }
          setReport(next);
          setError(null);
        } else {
          setError(String(next?.error ?? t("common.somethingWrong")));
        }
      } catch (err) {
        setError(String(err));
      }
    }
    try {
      const statuses = await api.systemctlShow(units);
      setAgents(Object.fromEntries(statuses.map((status) => [status.id, status])));
    } catch {
      /* the agent rows just stay unknown */
    }
  }, [isMac, units, t, toast]);

  useEffect(() => {
    if (!installing) void refresh();
  }, [refresh, installing]);

  // Live re-check: on macOS while the user flips switches in System Settings,
  // on Linux so a service started elsewhere shows up without a reload.
  const allGranted = Boolean(report?.all_granted);
  usePoll(() => refresh(), allGranted ? 15000 : 3000, ready && !installing);

  const request = async (id: string) => {
    setRequesting(id);
    try {
      const next = await api.macosRequestPermission(id);
      if (next && Array.isArray(next.permissions)) setReport(next);
      const item = next?.permissions?.find((p) => p.id === id);
      if (item?.status === "denied") {
        // macOS only prompts once; after that the pane has to be opened by hand.
        void api.openSettingsPane(PANE[id] ?? "Privacy").catch(() => {});
      } else {
        // TCC can settle a beat after the prompt closes, so re-check a few
        // times instead of waiting for the next poll tick (or a tab remount).
        for (const delay of [400, 1200, 2500]) {
          window.setTimeout(() => void refresh(), delay);
        }
      }
    } catch (err) {
      toast(t("setup.actions.requestFailed", { error: String(err) }), "error");
    } finally {
      setRequesting(null);
    }
  };

  const start = async (unit: string, action: "start" | "restart" = "start") => {
    setStarting(unit);
    try {
      const result = await api.systemctl(action, unit);
      if (!result.ok) toast(t("setup.agent.startFailed", { detail: (result.stderr || result.stdout).trim() }), "error");
      await refresh();
    } catch (err) {
      toast(t("setup.agent.startFailed", { detail: String(err) }), "error");
    } finally {
      setStarting(null);
    }
  };

  const granted = report?.permissions.filter((p) => p.status === "granted").length ?? 0;
  const total = report?.permissions.length ?? 0;
  const assistantKey = String(get("macos", "assistant_key", "right_command"));
  const dictationKey = String(get("macos", "dictation_key", "right_option"));
  const progress = useMemo(() => (total ? Math.round((granted / total) * 100) : 0), [granted, total]);

  if (ready && !isMac) {
    const runner = agents[LINUX_AGENT_UNITS[0]];
    const running = runner?.active_state === "active";
    const runnerInstalled = Boolean(runner && runner.load_state !== "not-found" && runner.load_state);
    return (
      <>
        <PageHeader title={t("setup.linuxTitle")} description={t("setup.linuxDescription")} />
        <PageBody>
          {/* status hero */}
          <section className="relative overflow-hidden rounded-lg bg-card p-5 shadow-card" aria-live="polite">
            <div className="flex items-center gap-4">
              <span
                className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl"
                style={{
                  color: running ? "var(--success)" : "var(--primary)",
                  background: `color-mix(in oklab, ${running ? "var(--success)" : "var(--primary)"} 13%, transparent)`,
                }}
              >
                <Icon name={running ? "check" : "power"} size={22} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[15px] font-semibold text-foreground">
                  {!runner
                    ? t("general.hero.checkingTitle")
                    : running
                      ? t("general.hero.runningTitle")
                      : t("general.hero.stoppedTitle")}
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {!runner
                    ? t("general.hero.checkingBody")
                    : running
                      ? t("general.hero.runningBody")
                      : t("general.hero.stoppedBody")}
                </p>
              </div>
              {runnerInstalled && (
                <Button
                  size="sm"
                  variant={running ? "secondary" : "primary"}
                  icon={running ? "refresh" : "play"}
                  loading={starting === LINUX_AGENT_UNITS[0]}
                  onClick={() => void start(LINUX_AGENT_UNITS[0], running ? "restart" : "start")}
                >
                  {running ? t("general.hero.restart") : t("general.hero.start")}
                </Button>
              )}
              <Button size="sm" variant="ghost" icon="refresh" onClick={() => void refresh()}>
                {t("common.refresh")}
              </Button>
            </div>
          </section>

          <Section title={t("general.services.title")} description={t("general.services.description")}>
            {LINUX_AGENT_UNITS.map((unit) => (
              <AgentRow key={unit} unit={unit} status={agents[unit]} onStart={() => void start(unit)} busy={starting === unit} />
            ))}
          </Section>

          <Section title={t("about.runtime.title")} description={t("setup.linuxInstallBody")}>
            <Row leading={<Tile icon="folder" />} title={t("about.runtime.repo")}>
              <Value>{info?.repo || "—"}</Value>
            </Row>
            <Row leading={<Tile icon="terminal" />} title={t("about.runtime.python")}>
              <Value>{info?.python || "—"}</Value>
            </Row>
            <Row leading={<Tile icon="sliders" />} title={t("about.runtime.config")}>
              <Value>{info?.config_path || "—"}</Value>
            </Row>
          </Section>

          <PageNote>{t("setup.linuxNote")}</PageNote>
        </PageBody>
      </>
    );
  }

  return (
    <>
      <PageHeader title={t("setup.title")} description={t("setup.description")} />
      <PageBody>
        {/* progress hero */}
        <section className="relative overflow-hidden rounded-lg bg-card p-5 shadow-card" aria-live="polite">
          <div className="flex items-center gap-4">
            <span
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl"
              style={{
                color: allGranted ? "var(--success)" : "var(--primary)",
                background: `color-mix(in oklab, ${allGranted ? "var(--success)" : "var(--primary)"} 13%, transparent)`,
              }}
            >
              <Icon name={allGranted ? "check" : "shield"} size={22} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[15px] font-semibold text-foreground">
                {allGranted ? t("setup.hero.doneTitle") : t("setup.hero.title")}
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {allGranted
                  ? t("setup.hero.doneBody", { assistant: displayMacKey(assistantKey), dictation: displayMacKey(dictationKey) })
                  : t("setup.hero.body")}
              </p>
              {total > 0 && (
                <div className="mt-3 flex items-center gap-3">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-wash-strong">
                    <div
                      className="h-full rounded-full transition-[width] duration-500"
                      style={{ width: `${progress}%`, background: allGranted ? "var(--success)" : "var(--primary)" }}
                    />
                  </div>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {t("setup.hero.progress", { granted, total })}
                  </span>
                </div>
              )}
            </div>
            <Button size="sm" variant="ghost" icon="refresh" onClick={() => void refresh()}>
              {t("common.refresh")}
            </Button>
          </div>
        </section>

        <Section title={t("setup.runtime.sectionTitle")} description={t("setup.runtime.sectionDescription")}>
          <RuntimeRow
            install={install}
            installing={installing}
            progress={installProgress}
            error={installError}
            onInstall={() => void runInstall()}
          />
        </Section>

        <Section title={t("setup.permissions.title")} description={t("setup.permissions.description")}>
          {installing || (!report && !error) ? (
            <SkeletonRows count={5} />
          ) : error && !report ? (
            <Row leading={<Tile icon="alert" tone="warn" />} title={t("setup.permissions.unavailable")} description={error}>
              <Button size="sm" onClick={() => void refresh()}>
                {t("common.retry")}
              </Button>
            </Row>
          ) : (
            report?.permissions.map((item) => (
              <PermissionRow key={item.id} item={item} onRequest={(id) => void request(id)} busy={requesting === id(item)} />
            ))
          )}
        </Section>

        <Section title={t("setup.agent.title")} description={t("setup.agent.description")}>
          {MAC_AGENT_UNITS.map((unit) => (
            <AgentRow key={unit} unit={unit} status={agents[unit]} onStart={() => void start(unit)} busy={starting === unit} />
          ))}
        </Section>

        <PageNote>
          {t("setup.note.process", { process: report?.process ?? "python" })}
          {" "}
          {t("setup.note.install")}
        </PageNote>
      </PageBody>
    </>
  );
}

function id(item: PermissionItem): string {
  return item.id;
}
