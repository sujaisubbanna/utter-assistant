import { useEffect, useState } from "react";

import { Icon } from "../components/icons";
import { PageBody, PageHeader } from "../components/PageHeader";
import {
  ConfigList,
  ConfigNumber,
  ConfigSelect,
  ConfigSwitch,
  SwitchSetting,
} from "../components/Setting";
import { Button } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Modal } from "../components/ui/Modal";
import { Row, Tile } from "../components/ui/Row";
import { useToast } from "../components/ui/Toast";
import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { humanizeError } from "../lib/errors";
import { usePlatform } from "../lib/platform";
import { DANGEROUS_OPS } from "../lib/services";

/**
 * App-targeted actions — how "<app> type …" reaches the target window.
 * The round-trip is Wayland-specific, so the knobs shown vary by platform:
 * Linux gets the full set plus [wayland]; macOS gets a note (no round-trip,
 * keys are posted straight to the target process); anything else gets mode only.
 */
function AppTargetingSection() {
  const { t } = useI18n();
  const { isMac, isWayland } = usePlatform();

  if (isMac) {
    return (
      <Section title={t("safety.targeting.title")} description={t("safety.targeting.description")}>
        <Row leading={<Tile icon="info" />} title={t("safety.targeting.macNote")} />
      </Section>
    );
  }

  // The `[wayland]` knobs only apply on a compositor Utter has a backend for
  // (niri/KWin). On X11 or an unknown compositor, targeting is not available,
  // so the tuning is hidden rather than shown inapplicable.
  if (!isWayland) {
    return (
      <Section title={t("safety.targeting.title")} description={t("safety.targeting.description")}>
        <ConfigSelect
          section="target"
          k="mode"
          title={t("safety.targeting.mode")}
          description={t("safety.targeting.modeHint")}
          fallback="round_trip"
          options={[
            { value: "round_trip", label: t("safety.targeting.modes.round_trip") },
            { value: "leave", label: t("safety.targeting.modes.leave") },
            { value: "off", label: t("safety.targeting.modes.off") },
          ]}
        />
        <Row leading={<Tile icon="info" />} title={t("safety.targeting.otherNote")} />
      </Section>
    );
  }

  return (
    <>
      <Section title={t("safety.targeting.title")} description={t("safety.targeting.description")}>
        <ConfigSelect
          section="target"
          k="mode"
          title={t("safety.targeting.mode")}
          description={t("safety.targeting.modeHint")}
          fallback="round_trip"
          options={[
            { value: "round_trip", label: t("safety.targeting.modes.round_trip") },
            { value: "leave", label: t("safety.targeting.modes.leave") },
            { value: "off", label: t("safety.targeting.modes.off") },
          ]}
        />
        <ConfigSelect
          section="target"
          k="restore"
          title={t("safety.targeting.restore")}
          description={t("safety.targeting.restoreHint")}
          fallback="if_unchanged"
          options={[
            { value: "if_unchanged", label: t("safety.targeting.restores.if_unchanged") },
            { value: "always", label: t("safety.targeting.restores.always") },
            { value: "never", label: t("safety.targeting.restores.never") },
          ]}
        />
        <ConfigNumber
          section="target"
          k="focus_timeout_ms"
          title={t("safety.targeting.timeout")}
          description={t("safety.targeting.timeoutHint")}
          fallback={500}
          min={0}
          max={5000}
          step={50}
          suffix={t("common.ms")}
        />
      </Section>

      <Section
        title={t("safety.targeting.wayland.title")}
        description={t("safety.targeting.wayland.description")}
      >
          <ConfigSelect
            section="wayland"
            k="cross_workspace"
            title={t("safety.targeting.wayland.crossWorkspace")}
            description={t("safety.targeting.wayland.crossWorkspaceHint")}
            fallback="auto"
            options={[
              { value: "auto", label: t("safety.targeting.wayland.crossWorkspaces.auto") },
              { value: "ask", label: t("safety.targeting.wayland.crossWorkspaces.ask") },
              { value: "allow", label: t("safety.targeting.wayland.crossWorkspaces.allow") },
              { value: "refuse", label: t("safety.targeting.wayland.crossWorkspaces.refuse") },
            ]}
          />
          <ConfigSwitch
            section="wayland"
            k="assume_animations_off"
            title={t("safety.targeting.wayland.animationsOff")}
            description={t("safety.targeting.wayland.animationsOffHint")}
            fallback={false}
          />
        </Section>
    </>
  );
}

export function SafetyPage() {
  const { t, tn } = useI18n();
  const toast = useToast();
  const [pending, setPending] = useState<(typeof DANGEROUS_OPS)[number] | null>(null);

  // The risky-op gate is enforced by the runner from its own config, so read
  // and write it there — `~/.config/utter/config.toml` is never consulted.
  const [enabledOps, setEnabledOps] = useState<string[]>([]);
  useEffect(() => {
    api
      .getRunnerPolicy()
      .then((policy) => setEnabledOps(policy.enabled_ops))
      .catch(() => {});
  }, []);

  const isEnabled = (op: string) => enabledOps.includes(op);
  const opName = (op: string) => {
    const def = DANGEROUS_OPS.find((item) => item.op === op);
    return def ? t(def.titleKey) : op;
  };

  const setOp = async (op: string, on: boolean) => {
    const next = on
      ? Array.from(new Set([...enabledOps, op])).sort()
      : enabledOps.filter((value) => value !== op);
    try {
      const policy = await api.setRunnerPolicy(next);
      setEnabledOps(policy.enabled_ops);
      toast(
        t(on ? "safety.risky.enabledToast" : "safety.risky.disabledToast", { name: opName(op) }),
        on ? "warn" : "ok",
      );
    } catch (error) {
      toast(t("common.saveFailed", { what: "policy.enabled_ops", error: humanizeError(error, t) }), "error");
    }
  };

  return (
    <>
      <PageHeader title={t("safety.title")} description={t("safety.description")} />
      <PageBody config>
        {enabledOps.length > 0 && (
          <div
            className="flex items-start gap-3 rounded-lg px-4 py-3.5"
            style={{
              boxShadow: "0 0 0 1px color-mix(in oklab, var(--destructive) 35%, transparent)",
              background: "color-mix(in oklab, var(--destructive) 7%, var(--card))",
            }}
            role="alert"
          >
            <Icon name="alert" size={17} className="mt-0.5 shrink-0 text-[color:var(--destructive)]" />
            <div>
              <div className="text-[13px] font-semibold text-foreground">
                {tn("safety.banner.title", enabledOps.length)}
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {t("safety.banner.body", { list: enabledOps.map(opName).join(", ") })}
              </p>
            </div>
          </div>
        )}

        <Section title={t("safety.confirm.title")} description={t("safety.confirm.description")}>
          <ConfigSwitch
            section="actions"
            k="confirm_enabled"
            title={t("safety.confirm.enable")}
            description={t("safety.confirm.enableHint")}
            fallback
          />
          <ConfigList
            section="actions"
            k="require_confirm"
            title={t("safety.confirm.words")}
            description={t("safety.confirm.wordsHint")}
            placeholder={t("safety.confirm.placeholder")}
          />
        </Section>

        <Section
          title={t("safety.risky.title")}
          description={t("safety.risky.description")}
          tone={enabledOps.length > 0 ? "danger" : "default"}
        >
          {DANGEROUS_OPS.map((item) => (
            <SwitchSetting
              key={item.op}
              leading={<Tile icon={item.op === "action.terminal" ? "terminal" : "keyboard"} tone={isEnabled(item.op) ? "danger" : "muted"} />}
              title={t(item.titleKey)}
              description={t(item.descKey)}
              checked={isEnabled(item.op)}
              onChange={(next) => {
                if (next) setPending(item);
                else void setOp(item.op, false);
              }}
            />
          ))}
        </Section>

        <AppTargetingSection />
      </PageBody>

      <Modal
        open={pending !== null}
        onClose={() => setPending(null)}
        title={t("safety.risky.confirmTitle", { name: pending ? t(pending.titleKey) : "" })}
        description={pending ? t(pending.descKey) : undefined}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPending(null)}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                if (pending) void setOp(pending.op, true);
                setPending(null);
              }}
            >
              {t("safety.risky.confirm")}
            </Button>
          </>
        }
      >
        <p className="text-[13px] text-muted-foreground">{t("safety.risky.confirmBody")}</p>
      </Modal>
    </>
  );
}
