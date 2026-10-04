import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Icon } from "../../components/icons";
import { LogoTile } from "../../components/Logo";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Section } from "../../components/ui/Card";
import { Progress } from "../../components/ui/Progress";
import { Row, Tile } from "../../components/ui/Row";
import { SkeletonRows } from "../../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../../components/ui/States";
import { useToast } from "../../components/ui/Toast";
import { LANG_NAMES, detectLang, useI18n, type LangPref } from "../../i18n";
import { api } from "../../lib/api";
import { kindLabelKey } from "../../lib/appKinds";
import { useConfig } from "../../lib/config";
import { useTauriEvent } from "../../lib/events";
import { humanBytes, parseJsonLine } from "../../lib/format";
import { usePoll } from "../../lib/hooks";
import { displayMacKey, displayName } from "../../lib/keys";
import { PULL_SOURCES } from "../../lib/links";
import type { ModelChoice, OnboardingData } from "../../lib/onboarding";
import { usePlatform } from "../../lib/platform";
import { normalizeSttBackend } from "../../lib/services";
import type { AppCatalogEntry, ModelEntry, PermissionItem, PermissionReport, Recommendation, UnitStatus } from "../../lib/types";
import { cn } from "../../lib/utils";
import {
  AppIcon,
  Feature,
  KeyCaptureModal,
  StepHeading,
  TierCard,
} from "./parts";
import {
  ICON as PERMISSION_ICON,
  LABEL_KEY as PERMISSION_LABEL,
  LINUX_AGENT_UNITS,
  MAC_AGENT_UNITS,
  PANE,
  PROMPTS,
  RESTART_ON_GRANT,
  WHY_KEY as PERMISSION_WHY,
} from "../Setup";

export interface NavApi {
  index: number;
  total: number;
  next: () => void;
  back: () => void;
  skip: () => void;
  goTo: (index: number) => void;
  finish: () => void;
  skipAll: () => void;
}

export interface StepProps {
  data: OnboardingData;
  commit: (patch: Partial<OnboardingData>) => void;
  nav: NavApi;
}

// --------------------------------------------------------------------------- //
// Welcome
// --------------------------------------------------------------------------- //

export function WelcomeStep({ nav }: StepProps) {
  const { t } = useI18n();
  return (
    <div className="flex flex-col items-center justify-center pb-10 pt-6 text-center">
      <span className="animate-pop">
        <LogoTile size={76} />
      </span>
      <div className="eyebrow mt-8">{t("onboarding.welcome.eyebrow")}</div>
      <h1 className="mt-2 max-w-[30rem] font-display text-[30px] font-semibold leading-[37px] tracking-[-0.025em] text-foreground">
        {t("onboarding.welcome.title")}
      </h1>
      <p className="mt-3 max-w-[34rem] text-[13.5px] leading-[21px] text-muted-foreground">
        {t("onboarding.welcome.body")}
      </p>
      <div className="mt-8 flex flex-col items-center gap-3">
        <Button
          variant="primary"
          iconRight="chevron-right"
          className="h-9 px-4 text-[13px]"
          onClick={nav.next}
        >
          {t("onboarding.welcome.start")}
        </Button>
        <button
          type="button"
          onClick={nav.skipAll}
          className="focus-ring rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          {t("onboarding.welcome.skip")}
        </button>
      </div>
      <p className="mt-10 flex items-center gap-1.5 text-[11.5px] text-muted-foreground/85">
        <Icon name="shield" size={13} className="text-[color:var(--success)]" />
        {t("onboarding.welcome.privacy")}
      </p>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Language
// --------------------------------------------------------------------------- //

export function LanguageStep({ data, commit }: StepProps) {
  const { t, pref, setPref } = useI18n();
  const current = data.language ?? pref;
  const options: { value: LangPref; label: string }[] = [
    { value: "system", label: t("language.system", { name: LANG_NAMES[detectLang()] }) },
    ...(Object.keys(LANG_NAMES) as (keyof typeof LANG_NAMES)[]).map((lang) => ({
      value: lang as LangPref,
      label: LANG_NAMES[lang],
    })),
  ];
  const choose = (value: LangPref) => {
    // Change the UI immediately: the rest of the wizard is the preview.
    setPref(value);
    commit({ language: value });
  };
  return (
    <>
      <StepHeading
        eyebrow={t("onboarding.language.eyebrow")}
        title={t("onboarding.language.title")}
        body={t("onboarding.language.body")}
      />
      <div
        role="radiogroup"
        aria-label={t("onboarding.language.title")}
        className="grid grid-cols-2 gap-2.5 sm:grid-cols-3"
      >
        {options.map((option) => {
          const selected = option.value === current;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => choose(option.value)}
              className={cn(
                "focus-ring flex items-center justify-between gap-2 rounded-lg bg-card px-3.5 py-3 text-left text-[13px] font-medium text-foreground shadow-card transition-[box-shadow,transform] duration-150 ease-out hover:shadow-raised",
                selected &&
                  "shadow-[0_0_0_1.5px_var(--primary),0_4px_14px_-8px_color-mix(in_oklab,var(--primary)_55%,transparent)]",
              )}
            >
              <span className="truncate">{option.label}</span>
              {selected && <Icon name="check" size={14} className="shrink-0 text-primary" strokeWidth={2.4} />}
            </button>
          );
        })}
      </div>
    </>
  );
}

// --------------------------------------------------------------------------- //
// What Utter does
// --------------------------------------------------------------------------- //

export function IntroStep({}: StepProps) {
  const { t } = useI18n();
  return (
    <>
      <StepHeading
        eyebrow={t("onboarding.intro.eyebrow")}
        title={t("onboarding.intro.title")}
        body={t("onboarding.intro.body")}
      />
      <div className="stagger flex flex-col gap-5 rounded-xl bg-card p-5 shadow-card sm:p-6">
        <Feature icon="mic" title={t("onboarding.intro.listenTitle")} body={t("onboarding.intro.listenBody")} />
        <Feature icon="zap" title={t("onboarding.intro.actTitle")} body={t("onboarding.intro.actBody")} />
        <Feature
          icon="lock"
          title={t("onboarding.intro.privateTitle")}
          body={t("onboarding.intro.privateBody")}
        />
      </div>
    </>
  );
}

// --------------------------------------------------------------------------- //
// Permissions (macOS prompts / Linux runner service)
// --------------------------------------------------------------------------- //

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
  const granted = item.status === "granted";
  const denied = item.status === "denied";
  return (
    <Row
      leading={
        <Tile
          icon={PERMISSION_ICON[item.id] ?? "shield"}
          tone={granted ? "ok" : denied ? "danger" : "muted"}
        />
      }
      title={
        <span className="flex items-center gap-2">
          {t(PERMISSION_LABEL[item.id] ?? "setup.permissions.other")}
          <Badge tone={granted ? "ok" : denied ? "danger" : "warn"} dot>
            {granted
              ? t("setup.status.granted")
              : denied
                ? t("setup.status.denied")
                : t("setup.status.notAsked")}
          </Badge>
        </span>
      }
      description={t(PERMISSION_WHY[item.id] ?? "setup.permissions.otherWhy")}
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

function PermissionsStepMac({
  data,
  commit,
}: StepProps) {
  const { t } = useI18n();
  const toast = useToast();
  const [report, setReport] = useState<PermissionReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requesting, setRequesting] = useState<string | null>(null);
  const grantedRef = useRef<Set<string> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.macosPermissions();
      if (next && Array.isArray(next.permissions)) {
        const nowGranted = new Set(
          next.permissions.filter((item) => item.status === "granted").map((item) => item.id),
        );
        const previous = grantedRef.current;
        grantedRef.current = nowGranted;
        if (previous && RESTART_ON_GRANT.some((id) => nowGranted.has(id) && !previous.has(id))) {
          void api.macosRestartAgents().catch(() => {});
        }
        setReport(next);
        setError(null);
      } else {
        setError(String(next?.error ?? t("common.somethingWrong")));
      }
    } catch (err) {
      setError(String(err));
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const allGranted = Boolean(report?.all_granted);
  usePoll(() => refresh(), allGranted ? 15000 : 3000, true);

  const request = async (id: string) => {
    setRequesting(id);
    try {
      const next = await api.macosRequestPermission(id);
      if (next && Array.isArray(next.permissions)) setReport(next);
      const item = next?.permissions?.find((p) => p.id === id);
      if (item?.status === "denied") {
        void api.openSettingsPane(PANE[id] ?? "Privacy").catch(() => {});
      } else {
        for (const delay of [400, 1200, 2500]) window.setTimeout(() => void refresh(), delay);
      }
    } catch (err) {
      toast(t("setup.actions.requestFailed", { error: String(err) }), "error");
    } finally {
      setRequesting(null);
    }
  };

  const granted = report?.permissions.filter((p) => p.status === "granted").length ?? 0;
  const total = report?.permissions.length ?? 0;
  const pct = total ? Math.round((granted / total) * 100) : 0;

  return (
    <>
      <StepHeading
        eyebrow={t("onboarding.permissions.eyebrow")}
        title={t("onboarding.permissions.title")}
        body={t("onboarding.permissions.bodyMac")}
      />
      <section className="mb-4 overflow-hidden rounded-xl bg-card p-5 shadow-card" aria-live="polite">
        <div className="flex items-center gap-4">
          <span
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl"
            style={{
              color: allGranted ? "var(--success)" : "var(--primary)",
              background: `color-mix(in oklab, ${allGranted ? "var(--success)" : "var(--primary)"} 13%, transparent)`,
            }}
          >
            <Icon name={allGranted ? "check" : "shield"} size={21} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[14px] font-semibold text-foreground">
              {allGranted ? t("onboarding.permissions.allGranted") : t("onboarding.permissions.title")}
            </div>
            {total > 0 && (
              <div className="mt-2.5 flex items-center gap-3">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-wash-strong">
                  <div
                    className="h-full rounded-full transition-[width] duration-500"
                    style={{ width: `${pct}%`, background: allGranted ? "var(--success)" : "var(--primary)" }}
                  />
                </div>
                <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                  {t("onboarding.permissions.grantedCount", { granted, total })}
                </span>
              </div>
            )}
          </div>
        </div>
      </section>

      {error && !report ? (
        <div className="overflow-hidden rounded-xl bg-card shadow-card">
          <ErrorState message={error} onRetry={() => void refresh()} />
        </div>
      ) : !report ? (
        <div className="overflow-hidden rounded-xl bg-card shadow-card">
          <SkeletonRows count={5} />
        </div>
      ) : (
        <Section title={t("setup.permissions.title")} description={t("setup.permissions.description")}>
          {report.permissions.map((item) => (
            <PermissionRow key={item.id} item={item} onRequest={(id) => void request(id)} busy={requesting === item.id} />
          ))}
        </Section>
      )}
    </>
  );
}

function PermissionsStepLinux({ data, commit }: StepProps) {
  const { t } = useI18n();
  const { isNiri, isKwin } = usePlatform();
  const [runner, setRunner] = useState<UnitStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const statuses = await api.systemctlShow(LINUX_AGENT_UNITS);
      setRunner(statuses.find((status) => status.id === "utter-runner") ?? statuses[0] ?? null);
    } catch {
      /* the row stays unknown */
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const running = runner?.active_state === "active";
  const installed = Boolean(runner && runner.load_state !== "not-found" && runner.load_state);
  usePoll(() => refresh(), running ? 15000 : 3000, true);

  const start = async () => {
    setBusy(true);
    try {
      await api.systemctl(running ? "restart" : "start", "utter-runner");
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <StepHeading
        eyebrow={t("onboarding.permissions.eyebrow")}
        title={t("onboarding.permissions.title")}
        body={t("onboarding.permissions.bodyLinux")}
      />
      <Section>
        <Row
          leading={<Tile icon="cpu" tone={running ? "ok" : installed ? "muted" : "warn"} />}
          title={t("onboarding.permissions.runnerTitle")}
          description={
            !runner
              ? t("general.services.checking")
              : running
                ? t("onboarding.permissions.running")
                : installed
                  ? t("onboarding.permissions.stopped")
                  : t("onboarding.permissions.missing")
          }
        >
          <span className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex">
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                !runner ? "bg-[var(--muted-foreground)]" : running ? "bg-[var(--success)]" : "bg-[var(--muted-foreground)]",
              )}
              aria-hidden="true"
            />
            {!runner
              ? t("general.services.checking")
              : running
                ? t("onboarding.permissions.running")
                : t("onboarding.permissions.stopped")}
          </span>
          {installed && (
            <Button
              size="sm"
              variant={running ? "secondary" : "primary"}
              icon={running ? "refresh" : "play"}
              loading={busy}
              onClick={() => void start()}
            >
              {running ? t("onboarding.permissions.restart") : t("onboarding.permissions.start")}
            </Button>
          )}
        </Row>
      </Section>
      {(isNiri || isKwin) && (
        <div className="mt-4 flex items-start gap-3 rounded-lg bg-wash px-4 py-3.5">
          <Icon name="info" size={16} className="mt-0.5 shrink-0 text-muted-foreground" />
          <p className="text-xs text-muted-foreground">{t("safety.targeting.wayland.description")}</p>
        </div>
      )}
      <p className="mt-4 px-0.5 text-xs text-muted-foreground/85">{t("onboarding.permissions.linuxNote")}</p>
    </>
  );
}

export function PermissionsStep(props: StepProps) {
  const { isMac } = usePlatform();
  return isMac ? <PermissionsStepMac {...props} /> : <PermissionsStepLinux {...props} />;
}

// --------------------------------------------------------------------------- //
// Shortcut keys
// --------------------------------------------------------------------------- //

function KeyRow({
  title,
  description,
  current,
  conflict,
  onCapture,
}: {
  title: string;
  description: string;
  current: string;
  conflict: boolean;
  onCapture: (name: string) => void;
}) {
  const { t } = useI18n();
  const { isMac } = usePlatform();
  const [open, setOpen] = useState(false);
  return (
    <Row title={title} description={description} leading={<Tile icon="keyboard" />}>
      <span className={cn("kbd", conflict && "shadow-[0_0_0_1px_var(--destructive)]")}>
        {current ? (isMac ? displayMacKey(current) : displayName(current)) : t("onboarding.keys.notSet")}
      </span>
      <Button size="sm" onClick={() => setOpen(true)}>
        {t("onboarding.keys.change")}
      </Button>
      <KeyCaptureModal
        open={open}
        title={title}
        current={current}
        onClose={() => setOpen(false)}
        onCaptured={(name) => {
          onCapture(name);
          setOpen(false);
        }}
      />
    </Row>
  );
}

export function KeysStep({ data, commit }: StepProps) {
  const { t } = useI18n();
  const { isMac } = usePlatform();
  const { get, set } = useConfig();

  const section = isMac ? "macos" : "ptt";
  const assistantField = "assistant_key";
  const dictationField = "dictation_key";
  const assistantDefault = isMac ? "right_command" : "KEY_INSERT";
  const dictationDefault = isMac ? "right_option" : "KEY_F13";

  const assistant = String(get(section, assistantField, data.assistantKey ?? assistantDefault));
  const dictation = String(get(section, dictationField, data.dictationKey ?? dictationDefault));
  const conflict = Boolean(assistant) && assistant === dictation;

  const setKey = (field: string, value: string) => {
    void set(section, field, value);
    commit(field === assistantField ? { assistantKey: value } : { dictationKey: value });
  };

  return (
    <>
      <StepHeading
        eyebrow={t("onboarding.keys.eyebrow")}
        title={t("onboarding.keys.title")}
        body={t("onboarding.keys.body")}
      />
      <Section>
        <KeyRow
          title={t("onboarding.keys.assistant")}
          description={t("onboarding.keys.assistantHint")}
          current={assistant}
          conflict={conflict}
          onCapture={(name) => setKey(assistantField, name)}
        />
        <KeyRow
          title={t("onboarding.keys.dictation")}
          description={t("onboarding.keys.dictationHint")}
          current={dictation}
          conflict={conflict}
          onCapture={(name) => setKey(dictationField, name)}
        />
      </Section>
      {conflict && (
        <p className="mt-3 flex items-center gap-1.5 px-0.5 text-xs text-[color:var(--destructive)]">
          <Icon name="alert" size={13} />
          {t("onboarding.keys.conflict")}
        </p>
      )}
      <p className="mt-4 px-0.5 text-xs text-muted-foreground/85">
        {isMac ? t("onboarding.keys.macNote") : t("onboarding.keys.linuxNote")}
      </p>
    </>
  );
}

// --------------------------------------------------------------------------- //
// Apps
// --------------------------------------------------------------------------- //

function VisualCheck({ checked }: { checked: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] transition-[background-color,box-shadow] duration-150",
        checked
          ? "bg-primary text-primary-foreground"
          : "bg-card text-transparent shadow-[inset_0_0_0_1px_var(--line-strong)]",
      )}
    >
      <Icon name="check" size={12} strokeWidth={2.6} className={checked ? "opacity-100" : "opacity-0"} />
    </span>
  );
}

export function AppsStep({ data, commit }: StepProps) {
  const { t } = useI18n();
  const [entries, setEntries] = useState<AppCatalogEntry[] | null>(null);
  const [detected, setDetected] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const curatedRef = useRef<Set<string>>(new Set());
  const selected = useMemo(() => new Set(data.apps ?? []), [data.apps]);

  const load = useCallback(async () => {
    setError(null);
    try {
      // Preferred: the rich catalogue (real icons, detection, opt-in state).
      const rich = (await api.appsList()) as { apps?: AppCatalogEntry[]; ok?: boolean };
      if (rich && Array.isArray(rich.apps)) {
        const list = rich.apps.filter((entry) => entry?.id && !entry.id.startsWith("generic-"));
        curatedRef.current = new Set(list.filter((entry) => entry.preselected).map((entry) => entry.id));
        setDetected(true);
        setEntries(list);
        return;
      }
    } catch {
      /* fall through to the profile loader */
    }
    try {
      const profiles = await api.appProfilesList();
      const list: AppCatalogEntry[] = profiles.profiles
        .filter((profile) => !profile.id.startsWith("generic-"))
        .map((profile) => ({
          id: profile.id,
          name: profile.name,
          kind: profile.kind,
          icon: null,
          enabled: true,
          preselected: profile.curated,
        }));
      curatedRef.current = new Set(list.filter((entry) => entry.preselected).map((entry) => entry.id));
      setDetected(false);
      setEntries(list);
    } catch (err) {
      setError(String(err));
      setEntries([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Apply the curated defaults once, then remember the user's own selection.
  // The picker is the opt-in gate, so the choice must reach the backend — not
  // just localStorage. `app_profiles_set_enabled` writes the override files the
  // assistant loader reads.
  useEffect(() => {
    if (!entries || data.appsLoaded) return;
    const defaults = entries.filter((entry) => entry.preselected).map((entry) => entry.id);
    commit({ apps: defaults, appsLoaded: true });
    if (defaults.length) {
      void api.appProfilesSetEnabled(defaults, true).catch(() => {});
    }
  }, [entries, data.appsLoaded, commit]);

  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    commit({ apps: [...next] });
    void api.appProfilesSetEnabled([id], next.has(id)).catch(() => {});
  };

  const selectAll = (on: boolean) => {
    const ids = (entries ?? []).map((entry) => entry.id);
    commit({ apps: on ? ids : [] });
    if (ids.length) void api.appProfilesSetEnabled(ids, on).catch(() => {});
  };

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const list = (entries ?? []).filter(
      (entry) =>
        !needle ||
        entry.name.toLowerCase().includes(needle) ||
        entry.id.toLowerCase().includes(needle),
    );
    const rank = (entry: AppCatalogEntry) => (entry.preselected ? 0 : 1);
    return [...list].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  }, [entries, query]);

  const recommended = visible.filter((entry) => curatedRef.current.has(entry.id));
  const others = visible.filter((entry) => !curatedRef.current.has(entry.id));
  const searching = Boolean(query.trim());

  const renderList = (list: AppCatalogEntry[]) => (
    <div className="overflow-hidden rounded-xl bg-card shadow-card">
      <div className="divide-y divide-line">
        {list.map((entry) => {
          const checked = selected.has(entry.id);
          return (
            <label
              key={entry.id}
              className={cn(
                "flex min-h-[52px] cursor-pointer items-center gap-3 px-3.5 py-2.5 transition-colors duration-150 hover:bg-wash",
                checked && "bg-[color-mix(in_oklab,var(--primary)_7%,var(--card))]",
              )}
            >
              <input
                type="checkbox"
                className="peer sr-only"
                checked={checked}
                onChange={() => toggle(entry.id)}
              />
              <span className="flex items-center peer-focus-visible:[&>span]:outline peer-focus-visible:[&>span]:outline-2 peer-focus-visible:[&>span]:outline-[var(--ring)] peer-focus-visible:[&>span]:outline-offset-2">
                <VisualCheck checked={checked} />
              </span>
              <AppIcon icon={entry.icon} kind={entry.kind} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium text-foreground">{entry.name}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {t(kindLabelKey(entry.kind))}
                </span>
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );

  return (
    <>
      <StepHeading
        eyebrow={t("onboarding.apps.eyebrow")}
        title={t("onboarding.apps.title")}
        body={t("onboarding.apps.body")}
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[12rem] flex-1">
          <Icon
            name="search"
            size={14}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            type="search"
            value={query}
            placeholder={t("apps.search")}
            aria-label={t("apps.search")}
            onChange={(event) => setQuery(event.target.value)}
            className="field h-8 w-full rounded-md pl-8 pr-3 text-[13px]"
          />
        </div>
        <Badge tone="accent">{t("onboarding.apps.selected", { count: selected.size })}</Badge>
        <Button size="sm" variant="ghost" onClick={() => selectAll(true)}>
          {t("onboarding.apps.selectAll")}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => selectAll(false)}>
          {t("common.clear")}
        </Button>
      </div>

      {error ? (
        <div className="overflow-hidden rounded-xl bg-card shadow-card">
          <ErrorState title={t("onboarding.apps.loadError")} message={error} onRetry={() => void load()} />
        </div>
      ) : entries === null ? (
        <div className="overflow-hidden rounded-xl bg-card shadow-card">
          <SkeletonRows count={6} />
        </div>
      ) : visible.length === 0 ? (
        <div className="overflow-hidden rounded-xl bg-card shadow-card">
          <EmptyState icon="search" title={t("onboarding.apps.emptyTitle")} description={t("onboarding.apps.emptyBody")} compact />
        </div>
      ) : searching || showAll ? (
        renderList(visible)
      ) : (
        <div className="space-y-4">
          {recommended.length > 0 && (
            <div>
              <div className="eyebrow mb-1.5 px-0.5">{t("onboarding.apps.recommended")}</div>
              {renderList(recommended)}
            </div>
          )}
          {others.length > 0 && (
            <div>
              <div className="eyebrow mb-1.5 px-0.5">{t("onboarding.apps.installed")}</div>
              {renderList(others)}
            </div>
          )}
        </div>
      )}

      {!detected && entries && entries.length > 0 && (
        <p className="mt-3 flex items-start gap-1.5 px-0.5 text-[11.5px] text-muted-foreground/85">
          <Icon name="info" size={13} className="mt-px shrink-0" />
          {t("onboarding.apps.fallbackNote")}
        </p>
      )}
      {!searching && entries && entries.length > 0 && (
        <button
          type="button"
          onClick={() => setShowAll((value) => !value)}
          className="focus-ring mt-3 rounded-md px-1 py-1 text-xs font-medium text-accent-text hover:underline"
        >
          {showAll ? t("onboarding.apps.showFewer") : t("onboarding.apps.showAll")}
        </button>
      )}
    </>
  );
}

// --------------------------------------------------------------------------- //
// Models
// --------------------------------------------------------------------------- //

interface Tier {
  id: ModelChoice;
  title: string;
  body: string;
  size: number;
  details: string[];
  sttModel?: string;
  backend?: string;
  macBackend?: string;
  vision?: { model: string; source: string } | null;
}

const STT_SIZES: Record<string, number> = {
  "tiny.en": 75e6,
  "base.en": 145e6,
  "small.en": 484e6,
  "distil-small.en": 166e6,
  small: 484e6,
  medium: 1.5e9,
  "large-v3-turbo": 1.6e9,
  "distil-large-v3": 1.5e9,
};

export function ModelsStep({ data, commit, nav }: StepProps) {
  const { t } = useI18n();
  const { isMac } = usePlatform();
  const { set, setMany } = useConfig();
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [recError, setRecError] = useState(false);
  const [models, setModels] = useState<ModelEntry[] | null>(null);
  const [choice, setChoice] = useState<ModelChoice>(data.modelChoice ?? "recommended");
  const [phase, setPhase] = useState<"idle" | "downloading" | "error">("idle");
  const [error, setError] = useState("");
  const [transferred, setTransferred] = useState(0);
  const [total, setTotal] = useState<number | null>(null);
  const [fraction, setFraction] = useState(0);
  const pullIdRef = useRef("");
  const pendingRef = useRef<Tier | null>(null);

  useEffect(() => {
    api.recommend().then(setRecommendation).catch(() => setRecError(true));
    api.modelsList().then((result) => setModels(result?.models ?? [])).catch(() => setModels([]));
  }, []);

  const sugg = recommendation?.suggestions;
  const hw = recommendation?.hardware;
  const gpu = Boolean(isMac || (hw?.gpus && hw.gpus.length > 0));
  const recModel = String(sugg?.stt?.model || "distil-small.en");
  const recBackend = normalizeSttBackend(String(sugg?.stt?.backend || "faster_whisper"));
  const visionModel = String(sugg?.vision?.model || "");
  const visionSource = visionModel && visionModel !== "none" ? PULL_SOURCES[visionModel] : undefined;
  const includeVision = !isMac && gpu && Boolean(visionSource);

  const tiers: Tier[] = isMac
    ? [
        {
          id: "recommended",
          title: t("onboarding.models.recommendedTitle"),
          body: t("onboarding.models.recommendedBody"),
          size: 0,
          details: [t("voice.mac.appleSpeech")],
          macBackend: "apple_speech",
        },
        {
          id: "minimal",
          title: t("onboarding.models.minimalTitle"),
          body: t("onboarding.models.minimalBody"),
          size: STT_SIZES["small.en"],
          details: [t("onboarding.models.stt", { model: "small.en" }), t("onboarding.models.willFetch")],
          macBackend: "whisper_cpp",
          sttModel: "small.en",
        },
        {
          id: "skip",
          title: t("onboarding.models.skipTitle"),
          body: t("onboarding.models.skipBody"),
          size: 0,
          details: [t("onboarding.models.rules")],
        },
      ]
    : [
        {
          id: "recommended",
          title: t("onboarding.models.recommendedTitle"),
          body: t("onboarding.models.recommendedBody"),
          size: (STT_SIZES[recModel] ?? 0) + (includeVision && visionSource ? PULL_SIZES[visionModel] ?? 0 : 0),
          details: [
            t("onboarding.models.stt", { model: recModel }),
            ...(includeVision && visionSource ? [t("onboarding.models.vision", { model: visionModel })] : []),
          ],
          sttModel: recModel,
          backend: recBackend,
          vision: includeVision && visionSource ? { model: visionModel, source: visionSource } : null,
        },
        {
          id: "minimal",
          title: t("onboarding.models.minimalTitle"),
          body: t("onboarding.models.minimalBody"),
          size: STT_SIZES["tiny.en"],
          details: [t("onboarding.models.stt", { model: "tiny.en" }), t("onboarding.models.willFetch")],
          sttModel: "tiny.en",
          backend: "faster_whisper",
        },
        {
          id: "skip",
          title: t("onboarding.models.skipTitle"),
          body: t("onboarding.models.skipBody"),
          size: 0,
          details: [t("onboarding.models.rules")],
        },
      ];

  const selectedTier = tiers.find((tier) => tier.id === choice) ?? tiers[0];
  const installedNames = new Set((models ?? []).map((model) => String(model.name ?? "")));
  const visionInstalled = Boolean(
    selectedTier.vision && [...installedNames].some((name) => name.includes(selectedTier.vision!.model)),
  );
  const needsDownload = Boolean(selectedTier.vision && !visionInstalled && phase !== "downloading");

  const applyConfig = useCallback(
    async (tier: Tier) => {
      if (tier.id === "skip") return;
      if (isMac) {
        if (tier.macBackend === "apple_speech") {
          await setMany("macos", { stt_backend: "apple_speech" });
        } else if (tier.macBackend) {
          await setMany("macos", { stt_backend: tier.macBackend, stt_fallback: tier.macBackend });
          if (tier.sttModel) await set("stt", "model", tier.sttModel);
        }
      } else {
        if (tier.backend && tier.sttModel) await setMany("stt", { backend: tier.backend, model: tier.sttModel });
        if (tier.vision) await setMany("vision", { enabled: true, model: tier.vision.model });
      }
    },
    [isMac, set, setMany],
  );

  const finish = useCallback(
    async (tier: Tier) => {
      await applyConfig(tier);
      commit({ modelChoice: tier.id });
      nav.next();
    },
    [applyConfig, commit, nav],
  );

  const startDownload = useCallback(
    async (tier: Tier) => {
      if (!tier.vision) return;
      const pullId = `onboarding-${Date.now()}`;
      pullIdRef.current = pullId;
      pendingRef.current = tier;
      setPhase("downloading");
      setError("");
      setFraction(0);
      setTransferred(0);
      setTotal(null);
      try {
        await api.startModelsPull(pullId, tier.vision.source, "latest");
      } catch (err) {
        setPhase("error");
        setError(String(err));
      }
    },
    [],
  );

  const onContinue = () => {
    if (phase === "downloading") return;
    if (phase === "error") {
      // Never trap the user: a failed download can be skipped, retried separately.
      void finish(selectedTier);
      return;
    }
    if (needsDownload) void startDownload(selectedTier);
    else void finish(selectedTier);
  };

  useTauriEvent<{ pullId: string; line: string }>("models://progress", (payload) => {
    if (payload.pullId !== pullIdRef.current) return;
    const event = parseJsonLine(payload.line);
    if (!event) return;
    if (event.event === "progress") {
      const downloaded = Number(event.downloaded ?? 0);
      const size = event.total == null ? null : Number(event.total);
      setTransferred(downloaded);
      setTotal(size);
      if (size) setFraction(Math.min(1, downloaded / size));
    } else if (event.event === "done") {
      setFraction(1);
    } else if (event.event === "error") {
      setPhase("error");
      setError(String(event.error));
    }
  });

  useTauriEvent<{ pullId: string; code: number }>("models://done", (payload) => {
    if (payload.pullId !== pullIdRef.current) return;
    if (payload.code === 0) {
      const tier = pendingRef.current;
      if (tier) void finish(tier);
    } else {
      setPhase("error");
      setError((prev) => prev || t("models.pull.exitFailed", { code: payload.code }));
    }
  });

  return (
    <>
      <StepHeading
        eyebrow={t("onboarding.models.eyebrow")}
        title={t("onboarding.models.title")}
        body={t("onboarding.models.body")}
      />
      <div role="radiogroup" aria-label={t("onboarding.models.title")} className="flex flex-col gap-3">
        {tiers.map((tier) => (
          <TierCard
            key={tier.id}
            selected={choice === tier.id}
            onSelect={() => {
              setChoice(tier.id);
              commit({ modelChoice: tier.id });
              setPhase("idle");
              setError("");
            }}
            title={tier.title}
            body={tier.body}
            badge={tier.id === "recommended" ? t("onboarding.models.badge") : undefined}
            sizeLabel={tier.size > 0 ? t("onboarding.models.total", { size: humanBytes(tier.size) }) : undefined}
            details={tier.details}
          />
        ))}
      </div>

      {recError && (
        <p className="mt-3 flex items-start gap-1.5 px-0.5 text-[11.5px] text-muted-foreground/85">
          <Icon name="info" size={13} className="mt-px shrink-0" />
          {t("onboarding.models.detectFailed")}
        </p>
      )}

      {phase !== "idle" && (
        <div className="mt-5 animate-fade-up rounded-xl bg-wash px-4 py-3.5">
          <div className="mb-2 flex items-center justify-between gap-4 text-xs">
            <span className="min-w-0 truncate font-medium text-foreground">
              {phase === "error"
                ? t("onboarding.models.failed", { error: error || t("common.unknown") })
                : t("models.pull.downloading")}
            </span>
            <span className="shrink-0 font-mono text-[11.5px] tabular-nums text-muted-foreground">
              {phase === "downloading" && transferred > 0
                ? total
                  ? t("models.pull.progress", { done: humanBytes(transferred), total: humanBytes(total) })
                  : humanBytes(transferred)
                : ""}
            </span>
          </div>
          {phase === "downloading" && (
            <Progress label={t("models.pull.downloading")} value={fraction} indeterminate={!total} />
          )}
        </div>
      )}

      <div className="mt-6 flex items-center gap-2.5">
        <Button
          variant="primary"
          iconRight={needsDownload ? "download" : "chevron-right"}
          loading={phase === "downloading"}
          disabled={phase === "downloading"}
          onClick={onContinue}
        >
          {phase === "downloading"
            ? t("models.pull.downloading")
            : phase === "error"
              ? t("onboarding.permissions.continueAnyway")
              : needsDownload
                ? t("common.download")
                : t("onboarding.next")}
        </Button>
        {phase === "error" && (
          <Button variant="ghost" icon="refresh" onClick={() => void startDownload(selectedTier)}>
            {t("common.retry")}
          </Button>
        )}
      </div>
      {phase === "idle" && selectedTier.vision && !needsDownload && (
        <p className="mt-3 flex items-center gap-1.5 px-0.5 text-[11.5px] text-muted-foreground/85">
          <Icon name="check" size={12} className="text-[color:var(--success)]" />
          {t("onboarding.models.installed")}
        </p>
      )}
    </>
  );
}

/** Disk-size estimates by vision model; shown before a download is accepted. */
const PULL_SIZES: Record<string, number> = {
  "UI-TARS-7B": 16e9,
  "UI-TARS-2B": 9e9,
};

// --------------------------------------------------------------------------- //
// First action
// --------------------------------------------------------------------------- //

export function FirstActionStep({ data }: StepProps) {
  const { t } = useI18n();
  const { isMac } = usePlatform();
  const { get } = useConfig();
  const section = isMac ? "macos" : "ptt";
  const key = String(
    get(section, "assistant_key", isMac ? "right_command" : "KEY_INSERT") || data.assistantKey || "",
  );
  const display = key ? (isMac ? displayMacKey(key) : displayName(key)) : t("onboarding.keys.notSet");
  const examples = [
    t("onboarding.firstAction.example1"),
    t("onboarding.firstAction.example2"),
    t("onboarding.firstAction.example3"),
  ];
  return (
    <>
      <StepHeading
        eyebrow={t("onboarding.firstAction.eyebrow")}
        title={t("onboarding.firstAction.title")}
        body={t("onboarding.firstAction.body", { key: display })}
      />
      <div className="rounded-xl bg-card p-6 text-center shadow-card">
        <span className="kbd h-10 px-4 text-[15px]">{display}</span>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
          {examples.map((example) => (
            <span
              key={example}
              className="rounded-full bg-wash px-3.5 py-1.5 text-[13px] text-foreground shadow-[inset_0_0_0_1px_var(--line)]"
            >
              “{example}”
            </span>
          ))}
        </div>
        <p className="mt-6 flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
          <Icon name="wave" size={14} className="text-accent-text" />
          {t("onboarding.firstAction.tip")}
        </p>
      </div>
    </>
  );
}

// --------------------------------------------------------------------------- //
// Done
// --------------------------------------------------------------------------- //

export function DoneStep({ data, nav }: StepProps) {
  const { t, lang } = useI18n();
  const { isMac } = usePlatform();
  const { get } = useConfig();
  const section = isMac ? "macos" : "ptt";
  const key = String(
    get(section, "assistant_key", isMac ? "right_command" : "KEY_INSERT") || data.assistantKey || "",
  );
  const display = key ? (isMac ? displayMacKey(key) : displayName(key)) : t("onboarding.keys.notSet");
  const modelLabel =
    data.modelChoice === "minimal"
      ? t("onboarding.done.modelsMinimal")
      : data.modelChoice === "skip"
        ? t("onboarding.done.modelsSkip")
        : t("onboarding.done.modelsRecommended");
  const rows: { label: string; value: string }[] = [
    { label: t("onboarding.done.summaryLanguage"), value: LANG_NAMES[lang] },
    { label: t("onboarding.done.summaryKeys"), value: display },
    { label: t("onboarding.done.summaryApps"), value: t("onboarding.apps.selected", { count: data.apps?.length ?? 0 }) },
    { label: t("onboarding.done.summaryModels"), value: modelLabel },
  ];
  return (
    <div className="flex flex-col items-center pb-8 pt-4 text-center">
      <span
        className="animate-pop flex h-16 w-16 items-center justify-center rounded-3xl"
        style={{
          color: "var(--success)",
          background: "color-mix(in oklab, var(--success) 14%, var(--card))",
          boxShadow: "inset 0 0 0 1px color-mix(in oklab, var(--success) 30%, transparent)",
        }}
      >
        <Icon name="check" size={30} strokeWidth={2.2} />
      </span>
      <div className="eyebrow mt-6">{t("onboarding.done.eyebrow")}</div>
      <h1 className="mt-2 font-display text-[28px] font-semibold leading-[34px] tracking-[-0.025em] text-foreground">
        {t("onboarding.done.title")}
      </h1>
      <p className="mt-2 max-w-[32rem] text-[13.5px] leading-[20px] text-muted-foreground">
        {t("onboarding.done.body", { key: display })}
      </p>

      <dl className="mt-8 w-full max-w-[30rem] overflow-hidden rounded-xl bg-card text-left shadow-card">
        {rows.map((row, index) => (
          <div
            key={row.label}
            className={cn("flex items-center justify-between gap-4 px-4 py-3", index > 0 && "border-t border-line")}
          >
            <dt className="text-xs text-muted-foreground">{row.label}</dt>
            <dd className="truncate text-[13px] font-medium text-foreground">{row.value}</dd>
          </div>
        ))}
      </dl>

      <Button
        variant="primary"
        iconRight="chevron-right"
        className="mt-8 h-9 px-4 text-[13px]"
        onClick={nav.finish}
      >
        {t("onboarding.finish")}
      </Button>
      <button
        type="button"
        onClick={nav.back}
        className="focus-ring mt-3 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        {t("onboarding.back")}
      </button>
    </div>
  );
}
