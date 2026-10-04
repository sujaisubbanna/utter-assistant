import { useCallback, useState } from "react";

import { Icon, type IconName } from "../components/icons";
import { ModelRequiredDialog } from "../components/ModelRequired";
import { PageBody, PageHeader } from "../components/PageHeader";
import { ConfigNumber, ConfigSwitch, ConfigText, SwitchSetting } from "../components/Setting";
import { Badge } from "../components/ui/Badge";
import { LinkButton } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Row } from "../components/ui/Row";
import { useT, type MessageKey } from "../i18n";
import { useConfig } from "../lib/config";
import { LINKS } from "../lib/links";
import { useModelStatus } from "../lib/models";
import { usePlatform } from "../lib/platform";

const TIERS: { id: string; icon: IconName }[] = [
  { id: "t0", icon: "window" },
  { id: "t1", icon: "hand" },
  { id: "t2", icon: "keyboard" },
  { id: "t3", icon: "eye" },
];

const TRUST: { icon: IconName; title: MessageKey; body: MessageKey }[] = [
  { icon: "lock", title: "perception.trust.selectTitle", body: "perception.trust.selectBody" },
  { icon: "shield", title: "perception.trust.blockTitle", body: "perception.trust.blockBody" },
  { icon: "eye", title: "perception.trust.orderTitle", body: "perception.trust.orderBody" },
];

export function PerceptionPage() {
  const t = useT();
  // On macOS the effective VLM endpoint/model come from [macos.runtime]
  // (resolve_vision overrides [vision]); only enabled/target_width are read
  // from [vision], and CUDA is never used.
  const { isMac } = usePlatform();
  const visionSection = isMac ? "macos.runtime" : "vision";
  const { get, setMany } = useConfig();
  const { need, storePath, refresh } = useModelStatus();
  const [askingModel, setAskingModel] = useState(false);
  const closeModel = useCallback(() => setAskingModel(false), []);
  const visionEnabled = Boolean(get("vision", "enabled", false));

  // Turning vision on needs its model. When it is missing and the store can
  // fetch it, ask first instead of enabling something that can't run.
  const setVision = (next: boolean) => {
    const target = need("vision");
    if (!next || !target || target.installed) {
      void setMany("vision", { enabled: next, ...(next && target ? { model: target.model } : {}) });
      return;
    }
    setAskingModel(true);
  };

  return (
    <>
      <PageHeader title={t("perception.title")} description={t("perception.description")} />
      <PageBody config>
        <Section title={t("perception.order.title")} description={t("perception.order.description")}>
          <ol className="grid grid-cols-4 divide-x divide-line max-[879px]:grid-cols-2 max-[879px]:divide-x-0">
            {TIERS.map((tier, index) => (
              <li key={tier.id} className="relative px-4 py-4">
                <div className="flex items-center gap-2">
                  <span
                    className={
                      index === 3
                        ? "flex h-6 w-6 items-center justify-center rounded-md bg-wash text-muted-foreground"
                        : "flex h-6 w-6 items-center justify-center rounded-md bg-accent-soft text-accent-text"
                    }
                  >
                    <Icon name={tier.icon} size={14} />
                  </span>
                  <span className="font-mono text-[10.5px] text-muted-foreground">{index + 1}</span>
                </div>
                <div className="mt-2.5 text-[13px] font-medium text-foreground">
                  {t(`perception.order.${tier.id}` as MessageKey)}
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {t(`perception.order.${tier.id}Body` as MessageKey)}
                </p>
              </li>
            ))}
          </ol>
        </Section>

        <Section title={t("perception.a11y.title")} description={t("perception.a11y.description")}>
          <ConfigSwitch
            section="perception"
            k="accessibility_enabled"
            title={t("perception.a11y.enable")}
            description={t("perception.a11y.enableHint")}
            fallback
          />
        </Section>

        <Section
          title={t("perception.vision.title")}
          description={t("perception.vision.description")}
          actions={<Badge tone="muted">{t("perception.vision.badge")}</Badge>}
        >
          {isMac ? (
            <ConfigSwitch
              section="vision"
              k="enabled"
              title={t("perception.vision.enable")}
              description={t("perception.vision.enableHint")}
              fallback
            />
          ) : (
            <SwitchSetting
              title={t("perception.vision.enable")}
              description={t("perception.vision.enableHint")}
              checked={visionEnabled}
              onChange={setVision}
            />
          )}
          <ConfigText
            section={visionSection}
            k={isMac ? "vision_model" : "model"}
            title={t("perception.vision.model")}
            description={t("perception.vision.modelHint")}
            fallback={isMac ? "llama3.2-vision:11b" : "uitars"}
            monospace
            width="w-44"
          />
          <Row title={t("perception.vision.getModel")} description={LINKS.uitars.replace("https://", "")}>
            <LinkButton href={LINKS.uitars} variant="secondary">
              {t("common.website")}
            </LinkButton>
          </Row>
          <ConfigText
            section={visionSection}
            k={isMac ? "vision_base_url" : "base_url"}
            title={t("perception.vision.endpoint")}
            placeholder={isMac ? "http://127.0.0.1:11434/v1" : "http://127.0.0.1:8000/v1"}
            monospace
          />
          <ConfigNumber
            section="vision"
            k="target_width"
            title={t("perception.vision.width")}
            description={t("perception.vision.widthHint")}
            fallback={1344}
            min={640}
            max={3840}
            step={64}
            suffix={t("common.px")}
          />
          {!isMac && (
            <ConfigText
              section="vision"
              k="cuda_visible_devices"
              title={t("perception.vision.gpu")}
              description={t("perception.vision.gpuHint")}
              placeholder="0"
              monospace
              width="w-20"
            />
          )}
        </Section>

        <Section title={t("perception.trust.title")} description={t("perception.trust.description")}>
          {TRUST.map((point) => (
            <div key={point.title} className="flex items-start gap-3 px-4 py-3.5">
              <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent-text">
                <Icon name={point.icon} size={15} />
              </span>
              <div className="min-w-0">
                <div className="text-[13px] font-medium text-foreground">{t(point.title)}</div>
                <p className="mt-0.5 text-xs text-muted-foreground">{t(point.body)}</p>
              </div>
            </div>
          ))}
        </Section>
      </PageBody>

      <ModelRequiredDialog
        open={askingModel}
        onClose={closeModel}
        need={need("vision")}
        modelsPath={storePath}
        onInstalled={() => {
          const target = need("vision");
          void setMany("vision", {
            enabled: true,
            ...(target ? { model: target.model } : {}),
          });
          void refresh();
        }}
      />
    </>
  );
}
