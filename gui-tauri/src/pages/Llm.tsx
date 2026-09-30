import { useState } from "react";

import { PageBody, PageHeader } from "../components/PageHeader";
import { ConfigRange, ConfigSwitch, ConfigText, SelectSetting } from "../components/Setting";
import { Badge } from "../components/ui/Badge";
import { Button, LinkButton } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Row, Tile } from "../components/ui/Row";
import { useToast } from "../components/ui/Toast";
import { useT } from "../i18n";
import { api } from "../lib/api";
import { useConfig } from "../lib/config";
import { linkFor } from "../lib/links";
import { LLM_PROVIDERS, optionLabel } from "../lib/services";

export function LlmPage() {
  const t = useT();
  const { get, set } = useConfig();
  const toast = useToast();
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const provider = String(get("router", "llm_provider", "vllm"));
  const baseUrl = String(get("router", "llm_base_url", ""));
  const providerDef = LLM_PROVIDERS.find((item) => item.value === provider);
  const providerLink = providerDef?.link ? linkFor(providerDef.link) : undefined;
  const probe = `${(baseUrl || "…").replace(/\/+$/, "")}/models`;

  const test = async () => {
    if (!baseUrl.startsWith("http")) {
      toast(t("llm.provider.noUrl"), "warn");
      return;
    }
    setTesting(true);
    setResult(null);
    try {
      const out = await api.testEndpoint(`${baseUrl.replace(/\/+$/, "")}/models`);
      const code = (out.stdout || "").trim();
      const good = out.ok && code.startsWith("2");
      const text = good
        ? t("llm.provider.ok", { code })
        : t("llm.provider.failed", { detail: code || out.stderr.trim() });
      setResult({ ok: good, text });
      toast(text, good ? "ok" : "error");
    } catch (error) {
      const text = t("llm.provider.failed", { detail: String(error) });
      setResult({ ok: false, text });
      toast(text, "error");
    } finally {
      setTesting(false);
    }
  };

  return (
    <>
      <PageHeader
        title={t("llm.title")}
        description={t("llm.description")}
        actions={
          <Badge tone="accent" dot>
            {t("llm.badge")}
          </Badge>
        }
      />
      <PageBody config>
        <Section title={t("llm.provider.title")} description={t("llm.provider.description")}>
          <SelectSetting
            leading={<Tile icon="sparkles" tone="accent" />}
            title={t("llm.provider.label")}
            value={provider}
            options={LLM_PROVIDERS.map((item) => ({ value: item.value, label: optionLabel(item, t) }))}
            extra={
              providerLink && providerDef ? (
                <LinkButton href={providerLink}>{t("llm.provider.getIt", { name: optionLabel(providerDef, t) })}</LinkButton>
              ) : undefined
            }
            onChange={(next) => {
              void set("router", "llm_provider", next);
              const fallback = LLM_PROVIDERS.find((item) => item.value === next)?.url ?? "";
              if (fallback && !baseUrl.trim()) void set("router", "llm_base_url", fallback);
            }}
          />
          <ConfigText
            section="router"
            k="llm_base_url"
            title={t("llm.provider.url")}
            description={t("llm.provider.urlHint")}
            placeholder="http://127.0.0.1:8001/v1"
            monospace
          />
          <ConfigText
            section="router"
            k="llm_model"
            title={t("llm.provider.model")}
            description={t("llm.provider.modelHint")}
            placeholder="qwen3-4b"
            monospace
          />
          <Row
            title={t("llm.provider.test")}
            description={
              result ? (
                <span style={{ color: result.ok ? "var(--success)" : "var(--destructive)" }}>{result.text}</span>
              ) : (
                <span className="font-mono text-[11.5px]">{t("llm.provider.testHint", { url: `GET ${probe}` })}</span>
              )
            }
          >
            <Button loading={testing} icon="zap" onClick={() => void test()}>
              {t("common.test")}
            </Button>
          </Row>
        </Section>

        <Section title={t("llm.behaviour.title")} description={t("llm.behaviour.description")}>
          <ConfigSwitch
            section="router"
            k="llm_fallback"
            title={t("llm.behaviour.fallback")}
            description={t("llm.behaviour.fallbackHint")}
            fallback
          />
          <ConfigSwitch
            section="router"
            k="decision_head_enabled"
            title={t("llm.behaviour.head")}
            description={t("llm.behaviour.headHint")}
            fallback
          />
          <ConfigRange
            section="router"
            k="decide_threshold"
            title={t("llm.behaviour.threshold")}
            description={t("llm.behaviour.thresholdHint")}
            fallback={0.5}
            min={0}
            max={1}
            step={0.05}
            format={(value) => `${Math.round(value * 100)}%`}
          />
        </Section>
      </PageBody>
    </>
  );
}
