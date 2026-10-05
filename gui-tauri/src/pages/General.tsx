import { useCallback, useEffect, useState } from "react";

import { LanguageSelect } from "../components/LanguageSelect";
import { ConfigList, ConfigNumber, ConfigSwitch } from "../components/Setting";
import { PrivacyCard } from "../components/Privacy";
import { DesktopColoursRow } from "../components/DesktopColours";
import { PageBody, PageHeader, PageNote } from "../components/PageHeader";
import { ThemeControl } from "../components/ThemeControl";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Menu } from "../components/ui/Menu";
import { Row, Tile } from "../components/ui/Row";
import { Select } from "../components/ui/Select";
import { SkeletonRows } from "../components/ui/Skeleton";
import { StatusDot, type DotTone } from "../components/ui/StatusDot";
import { ErrorState } from "../components/ui/States";
import { Switch } from "../components/ui/Switch";
import { useToast } from "../components/ui/Toast";
import { useI18n, type MessageKey } from "../i18n";
import { api } from "../lib/api";
import { useConfig } from "../lib/config";
import { humanizeError } from "../lib/errors";
import { usePoll } from "../lib/hooks";
import { resetOnboarding } from "../lib/onboarding";
import { optionLabel, SERVICES, TRIGGERS } from "../lib/services";
import { useRunnerStatus } from "../lib/status";
import type { UnitStatus } from "../lib/types";
import { sameJson } from "../lib/utils";

const RUNNER = "utter-runner";

function describeUnit(status?: UnitStatus): { tone: DotTone; key: MessageKey; raw?: string } {
  if (!status) return { tone: "unknown", key: "general.services.checking" };
  const load = status.load_state;
  const active = status.active_state;
  if (load === "not-found" || load === "masked" || !load) {
    return { tone: "unknown", key: "general.services.notInstalled" };
  }
  if (active === "active") return { tone: "ok", key: "general.services.active", raw: status.sub_state };
  if (active === "failed") return { tone: "error", key: "general.services.failed" };
  if (active === "activating") return { tone: "busy", key: "general.services.starting" };
  return { tone: "muted", key: "general.services.inactive", raw: active };
}

function StatusHero({ onStart, busy }: { onStart: () => void; busy: boolean }) {
  const { t, tn } = useI18n();
  const { connected, status, loading } = useRunnerStatus();
  const plugins = status?.plugins?.length ?? 0;
  const state = loading && !status ? "checking" : connected ? "running" : "stopped";
  const tone: DotTone = state === "checking" ? "busy" : state === "running" ? "ok" : "error";
  const color =
    state === "running" ? "var(--success)" : state === "stopped" ? "var(--destructive)" : "var(--primary)";

  return (
    <section
      className="relative overflow-hidden rounded-lg bg-card shadow-card"
      aria-live="polite"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-16 -top-24 h-56 w-56 rounded-full opacity-60 blur-2xl"
        style={{ background: `radial-gradient(closest-side, color-mix(in oklab, ${color} 22%, transparent), transparent)` }}
      />
      <div className="relative flex items-center gap-4 px-5 py-5">
        <span
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
          style={{ background: `color-mix(in oklab, ${color} 12%, transparent)` }}
        >
          <StatusDot tone={tone} className="h-2.5 w-2.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[15px] font-semibold tracking-[-0.01em] text-foreground">
            {t(`general.hero.${state}Title` as MessageKey)}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {status?.error && state === "stopped" ? status.error : t(`general.hero.${state}Body` as MessageKey)}
          </p>
        </div>
        {state === "running" && plugins > 0 && <Badge tone="neutral">{tn("status.plugins", plugins)}</Badge>}
        {state !== "checking" && (
          <Button
            variant={state === "running" ? "secondary" : "primary"}
            icon={state === "running" ? "refresh" : "power"}
            loading={busy}
            onClick={onStart}
          >
            {state === "running" ? t("general.hero.restart") : t("general.hero.start")}
          </Button>
        )}
      </div>
    </section>
  );
}

export function GeneralPage() {
  const { t } = useI18n();
  const toast = useToast();
  const { get, set } = useConfig();
  const { connected, reload: reloadStatus } = useRunnerStatus();
  const [units, setUnits] = useState<UnitStatus[] | null>(null);
  const [unitError, setUnitError] = useState<string | null>(null);
  const [enabled, setEnabled] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  // Real config location, honouring XDG_CONFIG_HOME — not a hardcoded path.
  const [configPath, setConfigPath] = useState("~/.config/utter/config.toml");

  useEffect(() => {
    api
      .appInfo()
      .then((info) => setConfigPath(info.config_path))
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    try {
      const [list, state] = await Promise.all([
        api.systemctlShow(SERVICES.map((service) => service.unit)),
        api.systemctl("is-enabled", RUNNER),
      ]);
      setUnits((prev) => (sameJson(prev, list) ? prev : list));
      setUnitError(null);
      const nextEnabled = (state.stdout || state.stderr).trim();
      setEnabled((prev) => (prev === nextEnabled ? prev : nextEnabled));
    } catch (error) {
      setUnitError(humanizeError(error, t));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  // This one shells out to systemctl; keep it slow and stop when backgrounded.
  usePoll(() => load(), 15000);

  const actionLabel = (action: string) =>
    action === "start" || action === "restart" || action === "stop"
      ? t(`general.services.${action}` as MessageKey)
      : action === "enable"
        ? t("common.enable")
        : t("common.disable");

  const control = async (action: string, unit: string) => {
    setBusy(unit);
    const name = t(SERVICES.find((service) => service.unit === unit)?.labelKey ?? "general.serviceNames.runner");
    try {
      const result = await api.systemctl(action, unit);
      const detail = humanizeError((result.stderr || result.stdout).trim().slice(0, 140), t);
      toast(
        result.ok
          ? t("general.services.done", { action: actionLabel(action), name })
          : t("general.services.failedAction", {
              action: actionLabel(action).toLowerCase(),
              name,
              detail: detail || t("common.unknown"),
            }),
        result.ok ? "ok" : "error",
      );
      await load();
      await reloadStatus();
    } finally {
      setBusy(null);
    }
  };

  const unitMap = new Map((units ?? []).map((unit) => [unit.id, unit]));
  const installed = enabled && !["not-found", "masked"].includes(enabled);
  const trigger = String(get("general", "trigger", "hotkey"));
  const sleepOnIdle = Boolean(get("sleep", "on_idle", true));

  return (
    <>
      <PageHeader title={t("general.title")} description={t("general.description")} />
      <PageBody>
        <PrivacyCard />
        <StatusHero
          busy={busy === RUNNER}
          onStart={() => void control(connected ? "restart" : "start", RUNNER)}
        />

        <Section title={t("general.startup.title")} description={t("general.startup.description")}>
          <Row
            leading={<Tile icon="power" />}
            title={t("general.startup.login")}
            description={
              enabled === "enabled"
                ? t("general.startup.loginOn")
                : installed
                  ? t("general.startup.loginOff")
                  : t("general.startup.loginMissing")
            }
          >
            <Switch
              checked={enabled === "enabled"}
              disabled={!installed || busy === RUNNER}
              ariaLabel={t("general.startup.login")}
              onCheckedChange={(next) => void control(next ? "enable" : "disable", RUNNER)}
            />
          </Row>
          <Row leading={<Tile icon="mic" />} title={t("general.trigger.label")} description={t("general.trigger.hint")}>
            <Select
              className="w-56"
              ariaLabel={t("general.trigger.label")}
              value={TRIGGERS.some((item) => item.value === trigger) ? trigger : "hotkey"}
              onChange={(next) => void set("general", "trigger", next)}
              options={TRIGGERS.map((item) => ({ value: item.value, label: optionLabel(item, t) }))}
            />
          </Row>
        </Section>

        <Section title={t("general.sleep.title")} description={t("general.sleep.description")}>
          <ConfigSwitch
            section="sleep"
            k="enabled"
            title={t("general.sleep.enable")}
            description={t("general.sleep.enableHint")}
            fallback
          />
          <ConfigList
            section="sleep"
            k="trigger"
            title={t("general.sleep.trigger")}
            description={t("general.sleep.triggerHint")}
            placeholder="go to sleep"
            fallback={["go to sleep"]}
          />
          <ConfigSwitch
            section="sleep"
            k="unload_speech"
            title={t("general.sleep.speech")}
            description={t("general.sleep.speechHint")}
            fallback
          />
          <ConfigSwitch
            section="sleep"
            k="on_idle"
            title={t("general.sleep.idle")}
            description={t("general.sleep.idleHint")}
            fallback
          />
          <ConfigNumber
            section="sleep"
            k="idle_minutes"
            title={t("general.sleep.idleMinutes")}
            description={t("general.sleep.idleMinutesHint")}
            fallback={15}
            min={1}
            max={1440}
            step={1}
            suffix={t("general.sleep.minutesUnit")}
            disabled={!sleepOnIdle}
          />
        </Section>

        <Section title={t("general.appearance.title")} >
          <Row leading={<Tile icon="sun" />} title={t("general.appearance.theme")} description={t("general.appearance.themeHint")}>
            <ThemeControl />
          </Row>
          <DesktopColoursRow />
          <Row leading={<Tile icon="globe" />} title={t("language.label")} description={t("language.description")}>
            <LanguageSelect className="w-56" />
          </Row>
        </Section>

        <Section title={t("general.services.title")} description={t("general.services.description")}>
          {unitError && units === null ? (
            <ErrorState message={unitError} onRetry={() => void load()} />
          ) : units === null ? (
            <SkeletonRows count={5} />
          ) : (
            SERVICES.map((service) => {
              const info = describeUnit(unitMap.get(service.unit));
              const name = t(service.labelKey);
              return (
                <Row
                  key={service.unit}
                  leading={
                    <span className="flex w-7 justify-center">
                      <StatusDot tone={info.tone} />
                    </span>
                  }
                  title={name}
                  description={t(service.descKey)}
                >
                  <span className="hidden text-xs text-muted-foreground sm:inline" title={`${service.unit}.service${info.raw ? ` · ${info.raw}` : ""}`}>
                    {t(info.key)}
                  </span>
                  <Menu
                    label={t("general.services.control", { name })}
                    items={[
                      {
                        label: t("general.services.start"),
                        icon: "play",
                        disabled: busy === service.unit,
                        onSelect: () => void control("start", service.unit),
                      },
                      {
                        label: t("general.services.restart"),
                        icon: "refresh",
                        disabled: busy === service.unit,
                        onSelect: () => void control("restart", service.unit),
                      },
                      { separator: true },
                      {
                        label: t("general.services.stop"),
                        icon: "square",
                        danger: true,
                        disabled: busy === service.unit,
                        onSelect: () => void control("stop", service.unit),
                      },
                    ]}
                  />
                </Row>
              );
            })
          )}
        </Section>

        <Section title={t("nav.setup")} description={t("onboarding.rerunHint")}>
          <Row leading={<Tile icon="refresh" />} title={t("onboarding.rerun")}>
            <Button
              size="sm"
              icon="refresh"
              onClick={() => {
                resetOnboarding();
                window.location.hash = "";
                window.location.reload();
              }}
            >
              {t("onboarding.rerun")}
            </Button>
          </Row>
        </Section>

        <PageNote>
          {t("general.footer", { path: configPath })}
        </PageNote>
      </PageBody>
    </>
  );
}

