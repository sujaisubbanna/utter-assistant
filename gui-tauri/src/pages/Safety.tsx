import { useState } from "react";

import { Icon } from "../components/icons";
import { PageBody, PageHeader } from "../components/PageHeader";
import { ConfigList, ConfigNumber, ConfigSwitch, SwitchSetting } from "../components/Setting";
import { Button } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Modal } from "../components/ui/Modal";
import { Tile } from "../components/ui/Row";
import { useToast } from "../components/ui/Toast";
import { useI18n } from "../i18n";
import { useConfig } from "../lib/config";
import { DANGEROUS_OPS } from "../lib/services";

export function SafetyPage() {
  const { t, tn } = useI18n();
  const { get, set } = useConfig();
  const toast = useToast();
  const [pending, setPending] = useState<(typeof DANGEROUS_OPS)[number] | null>(null);

  const enabledOps = get<string[]>("policy", "enabled_ops", []);
  const isEnabled = (op: string) => enabledOps.includes(op);
  const opName = (op: string) => {
    const def = DANGEROUS_OPS.find((item) => item.op === op);
    return def ? t(def.titleKey) : op;
  };

  const setOp = async (op: string, on: boolean) => {
    const next = on
      ? Array.from(new Set([...enabledOps, op])).sort()
      : enabledOps.filter((value) => value !== op);
    await set("policy", "enabled_ops", next);
    toast(t(on ? "safety.risky.enabledToast" : "safety.risky.disabledToast", { name: opName(op) }), on ? "warn" : "ok");
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

        <Section title={t("safety.limits.title")} description={t("safety.limits.description")}>
          <ConfigList
            section="policy"
            k="allow_commands"
            title={t("safety.limits.commands")}
            description={t("safety.limits.commandsHint")}
            placeholder="ls, cat, git"
          />
          <ConfigList
            section="policy"
            k="blocked_phrases"
            title={t("safety.limits.blocked")}
            description={t("safety.limits.blockedHint")}
            placeholder="rm -rf, shutdown"
          />
        </Section>

        <Section title={t("safety.tuning.title")} description={t("safety.tuning.description")}>
          <ConfigNumber
            section="actions"
            k="click_duration_ms"
            title={t("safety.tuning.click")}
            description={t("safety.tuning.clickHint")}
            fallback={40}
            min={0}
            max={1000}
            step={5}
            suffix={t("common.ms")}
          />
        </Section>
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
