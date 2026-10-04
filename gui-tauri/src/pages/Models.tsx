import { useCallback, useEffect, useRef, useState } from "react";

import { PageBody, PageHeader } from "../components/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button, LinkButton } from "../components/ui/Button";
import { Section } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import { Modal } from "../components/ui/Modal";
import { Progress } from "../components/ui/Progress";
import { Row, Tile, Value } from "../components/ui/Row";
import { SkeletonRows } from "../components/ui/Skeleton";
import { EmptyState, ErrorState } from "../components/ui/States";
import { useToast } from "../components/ui/Toast";
import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { useConfig } from "../lib/config";
import { useTauriEvent } from "../lib/events";
import { humanBytes, parseJsonLine } from "../lib/format";
import { HF_MODELS, LINKS, PULL_SOURCES } from "../lib/links";
import { normalizeSttBackend } from "../lib/services";
import type { AppInfo, ModelEntry, Recommendation } from "../lib/types";

type PullPhase = "idle" | "starting" | "downloading" | "done" | "error";

interface PullState {
  active: boolean;
  phase: PullPhase;
  name: string;
  error: string;
  downloaded: number;
  total: number | null;
  fraction: number;
  indeterminate: boolean;
}

const IDLE_PULL: PullState = {
  active: false,
  phase: "idle",
  name: "",
  error: "",
  downloaded: 0,
  total: null,
  fraction: 0,
  indeterminate: false,
};

export function ModelsPage() {
  const { t, tn } = useI18n();
  const toast = useToast();
  const { setMany } = useConfig();
  const [models, setModels] = useState<ModelEntry[] | null>(null);
  const [storeRoot, setStoreRoot] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [recError, setRecError] = useState(false);
  const [source, setSource] = useState("");
  const [tag, setTag] = useState("latest");
  const [pull, setPull] = useState<PullState>(IDLE_PULL);
  const [removing, setRemoving] = useState<ModelEntry | null>(null);
  const [pruning, setPruning] = useState(false);
  const [loading, setLoading] = useState(false);
  const pullId = useRef("");
  const sourceRef = useRef<HTMLInputElement>(null);

  const loadModels = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.modelsList();
      setModels(data?.models ?? []);
      setStoreRoot(data?.store?.root ?? null);
      setError(null);
    } catch (err) {
      setError(String((err as Error)?.message ?? err));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRecommendation = useCallback(async () => {
    setRecommendation(null);
    setRecError(false);
    try {
      setRecommendation(await api.recommend());
    } catch {
      setRecError(true);
    }
  }, []);

  useEffect(() => {
    void loadModels();
    void loadRecommendation();
    api.appInfo().then(setInfo).catch(() => {});
  }, [loadModels, loadRecommendation]);

  useTauriEvent<{ pullId: string; line: string }>("models://progress", (payload) => {
    if (payload.pullId !== pullId.current) return;
    const event = parseJsonLine(payload.line);
    if (!event) return;
    const kind = event.event;
    if (kind === "start") {
      setPull((prev) => ({ ...prev, phase: "downloading", name: `${event.name}:${event.tag}`, indeterminate: true }));
    } else if (kind === "progress") {
      const downloaded = Number(event.downloaded ?? 0);
      const total = event.total == null ? null : Number(event.total);
      setPull((prev) => ({
        ...prev,
        phase: "downloading",
        name: prev.name || String(event.name ?? ""),
        downloaded,
        total,
        indeterminate: total == null,
        fraction: total ? Math.min(1, downloaded / total) : prev.fraction,
      }));
    } else if (kind === "done") {
      setPull((prev) => ({
        ...prev,
        phase: "done",
        fraction: 1,
        indeterminate: false,
        downloaded: Number(event.bytes ?? prev.downloaded),
      }));
    } else if (kind === "error") {
      setPull((prev) => ({ ...prev, phase: "error", error: String(event.error), indeterminate: false }));
    }
  });

  useTauriEvent<{ pullId: string; code: number }>("models://done", (payload) => {
    if (payload.pullId !== pullId.current) return;
    setPull((prev) => ({
      ...prev,
      active: false,
      indeterminate: false,
      phase: payload.code === 0 ? "done" : "error",
      error: payload.code === 0 ? "" : prev.error || t("models.pull.exitFailed", { code: payload.code }),
    }));
    void loadModels();
  });

  const startPull = async () => {
    if (!source.trim()) {
      toast(t("models.pull.needSource"), "warn");
      sourceRef.current?.focus();
      return;
    }
    const id = `pull-${Date.now()}`;
    pullId.current = id;
    setPull({ ...IDLE_PULL, active: true, phase: "starting", name: source.trim(), indeterminate: true });
    try {
      await api.startModelsPull(id, source.trim(), tag.trim() || "latest");
      setSource("");
    } catch (err) {
      setPull({ ...IDLE_PULL, phase: "error", error: String(err) });
      toast(t("models.pull.failed", { error: String(err) }), "error");
    }
  };

  const cancelPull = async () => {
    if (!pullId.current) return;
    await api.cancelModelsPull(pullId.current).catch(() => {});
  };

  const prefill = (value: string, name: string) => {
    setSource(value);
    toast(t("models.pull.prefilled", { name }), "info");
    window.setTimeout(() => {
      sourceRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      sourceRef.current?.focus();
    }, 60);
  };

  const remove = async (entry: ModelEntry) => {
    const name = `${entry.name}:${entry.tag}`;
    try {
      const result = await api.modelsRemove(name);
      toast(
        result.ok
          ? t("models.installed.removed", { name })
          : t("models.installed.removeFailed", { detail: (result.stderr || "").slice(0, 120) }),
        result.ok ? "ok" : "error",
      );
    } catch (err) {
      toast(t("models.installed.removeFailed", { detail: String(err) }), "error");
    } finally {
      setRemoving(null);
      void loadModels();
    }
  };

  const prune = async () => {
    setPruning(true);
    try {
      const result = await api.modelsPrune();
      const data = parseJsonLine(result.stdout) ?? {};
      const removed =
        ((data.removed_partials as unknown[])?.length ?? 0) + ((data.removed_blobs as unknown[])?.length ?? 0);
      toast(result.ok ? tn("models.storage.cleaned", removed) : t("models.storage.cleanFailed"), result.ok ? "ok" : "error");
    } catch {
      toast(t("models.storage.cleanFailed"), "error");
    } finally {
      setPruning(false);
      void loadModels();
    }
  };

  const totalBytes = (models ?? []).reduce((sum, model) => sum + (model.bytes ?? 0), 0);
  const suggestions = recommendation?.suggestions;
  const hardware = recommendation?.hardware;
  // Prefer the live store root reported by the CLI, then the backend's path,
  // then the documented default location.
  const storePath = storeRoot ?? info?.models_path ?? "~/.local/share/utter-models";

  const useStt = () => {
    const stt = (suggestions?.stt ?? {}) as Record<string, unknown>;
    const backend = normalizeSttBackend(String(stt.backend ?? "faster_whisper"));
    void setMany("stt", {
      backend,
      model: stt.model ?? "",
      ...(stt.device ? { device: stt.device } : {}),
    });
    toast(t("models.recommended.applied"), "ok");
  };

  const visionModel = String(suggestions?.vision?.model ?? "");
  const visionSource = PULL_SOURCES[visionModel];
  const decisionValue = `${suggestions?.decision_llm?.model ?? "?"} ${suggestions?.decision_llm?.quant ?? ""}`.trim();

  return (
    <>
      <PageHeader
        title={t("models.title")}
        description={t("models.description")}
        actions={
          <Button icon="refresh" variant="ghost" loading={loading} onClick={() => void loadModels()}>
            {t("common.refresh")}
          </Button>
        }
      />
      <PageBody>
        <Section title={t("models.installed.title")} description={t("models.installed.description", { path: storePath })}>
          {error ? (
            <ErrorState title={t("models.installed.loadError")} message={error} onRetry={() => void loadModels()} />
          ) : models === null ? (
            <SkeletonRows count={2} />
          ) : models.length === 0 ? (
            <EmptyState
              icon="box"
              title={t("models.installed.emptyTitle")}
              description={t("models.installed.emptyBody")}
              action={<LinkButton href={HF_MODELS} variant="secondary">{t("models.pull.browseHf")}</LinkButton>}
            />
          ) : (
            models.map((model) => (
              <Row
                key={`${model.name}:${model.tag}`}
                leading={<Tile icon="box" tone="accent" />}
                title={`${model.name}:${model.tag}`}
                description={t("models.installed.meta", {
                  size: humanBytes(model.bytes),
                  files: tn("models.installed.files", model.files ?? 0),
                })}
              >
                {model.host && <Value>{model.host}</Value>}
                <Button variant="ghost" size="sm" icon="trash" onClick={() => setRemoving(model)}>
                  {t("models.installed.remove")}
                </Button>
              </Row>
            ))
          )}
        </Section>

        <Section
          title={t("models.recommended.title")}
          description={t("models.recommended.description")}
          actions={
            <Button size="sm" variant="ghost" icon="refresh" onClick={() => void loadRecommendation()}>
              {t("models.recommended.detect")}
            </Button>
          }
        >
          {recError ? (
            <ErrorState title={t("models.recommended.unavailable")} onRetry={() => void loadRecommendation()} />
          ) : !suggestions ? (
            <SkeletonRows count={4} />
          ) : (
            <>
              {hardware && (
                <div className="flex items-center gap-3 bg-wash px-4 py-3">
                  <Tile icon="cpu" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-medium text-foreground">
                      {hardware.cpu?.model || t("common.unknown")}
                    </div>
                    <div className="mt-0.5 flex flex-wrap gap-1.5">
                      <Badge tone="muted">{t("models.recommended.ram", { ram: hardware.ram_gb ?? 0 })}</Badge>
                      {hardware.gpus && hardware.gpus.length > 0 ? (
                        hardware.gpus.map((gpu) => (
                          <Badge key={gpu.name} tone="muted">
                            {gpu.name} · {gpu.vram_gb ?? 0} GB
                          </Badge>
                        ))
                      ) : (
                        <Badge tone="muted">{t("models.recommended.noGpu")}</Badge>
                      )}
                    </div>
                  </div>
                </div>
              )}
              <RecRow
                icon="mic"
                title={t("models.recommended.stt")}
                value={`${suggestions.stt?.backend ?? "?"} · ${suggestions.stt?.model ?? "?"}`}
                reason={String(suggestions.stt?.reason ?? "")}
                link={<LinkButton href={LINKS.faster_whisper}>{t("models.recommended.getIt")}</LinkButton>}
                onUse={useStt}
                useLabel={t("common.use")}
              />
              <RecRow
                icon="sparkles"
                title={t("models.recommended.decision")}
                value={decisionValue}
                reason={String(suggestions.decision_llm?.reason ?? "")}
                link={
                  <LinkButton href={`${HF_MODELS}?search=${encodeURIComponent(String(suggestions.decision_llm?.quant ?? "awq"))}`}>
                    {t("models.recommended.browse")}
                  </LinkButton>
                }
                useLabel={t("common.use")}
                onUse={() => {
                  void setMany("router", { llm_model: decisionValue });
                  toast(t("models.recommended.decisionApplied"), "ok");
                }}
              />
              <RecRow
                icon="eye"
                title={t("models.recommended.vision")}
                value={visionModel || "?"}
                reason={String(suggestions.vision?.reason ?? "")}
                link={
                  visionSource ? (
                    <Button size="sm" variant="link" icon="download" onClick={() => prefill(visionSource, visionModel)}>
                      {t("common.download")}
                    </Button>
                  ) : (
                    <LinkButton href={LINKS.uitars}>{t("models.recommended.getIt")}</LinkButton>
                  )
                }
                useLabel={t("common.use")}
                onUse={() => {
                  if (visionModel && visionModel !== "none") {
                    void setMany("vision", { enabled: true, model: visionModel });
                    toast(t("models.recommended.visionApplied"), "ok");
                  } else {
                    void setMany("vision", { enabled: false });
                    toast(t("models.recommended.visionOff"), "ok");
                  }
                }}
              />
              {suggestions.zero_model_mode && (
                <Row
                  leading={<Tile icon="check-circle" tone="ok" />}
                  title={t("models.recommended.zero")}
                  description={t("models.recommended.zeroBody")}
                >
                  <Badge tone="ok" dot>
                    {t("models.recommended.ready")}
                  </Badge>
                </Row>
              )}
            </>
          )}
        </Section>

        <Section title={t("models.pull.title")} description={t("models.pull.description")}>
          <Row title={t("models.pull.source")} description={t("models.pull.sourceHint")}>
            <Input
              ref={sourceRef}
              value={source}
              onChange={(event) => setSource(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void startPull();
              }}
              placeholder="hf:org/name"
              className="w-64 font-mono text-[12px]"
              aria-label={t("models.pull.source")}
            />
          </Row>
          <Row title={t("models.pull.tag")} description={t("models.pull.tagHint")}>
            <Input
              value={tag}
              onChange={(event) => setTag(event.target.value)}
              className="w-32 font-mono text-[12px]"
              aria-label={t("models.pull.tag")}
            />
          </Row>
          <div className="flex items-center gap-3 px-4 py-3">
            <LinkButton href={HF_MODELS} variant="ghost">
              {t("models.pull.browseHf")}
            </LinkButton>
            <div className="ml-auto flex items-center gap-2">
              {pull.active && (
                <Button variant="ghost" icon="square" onClick={() => void cancelPull()}>
                  {t("models.pull.cancel")}
                </Button>
              )}
              <Button variant="primary" icon="download" loading={pull.active} onClick={() => void startPull()}>
                {pull.active ? t("models.pull.downloading") : t("models.pull.start")}
              </Button>
            </div>
          </div>
          {pull.phase !== "idle" && (
            <div className="animate-fade-up space-y-2 bg-wash px-4 py-3.5">
              <div className="flex items-center justify-between gap-4 text-xs">
                <span className="min-w-0 truncate font-medium text-foreground">
                  {pull.phase === "done"
                    ? t("models.pull.done")
                    : pull.phase === "error"
                      ? t("models.pull.failed", { error: pull.error })
                      : pull.phase === "starting"
                        ? t("models.pull.starting")
                        : pull.name}
                </span>
                <span className="shrink-0 font-mono text-[11.5px] tabular-nums text-muted-foreground">
                  {pull.downloaded > 0
                    ? pull.total
                      ? t("models.pull.progress", { done: humanBytes(pull.downloaded), total: humanBytes(pull.total) })
                      : humanBytes(pull.downloaded)
                    : ""}
                </span>
              </div>
              <Progress
                label={t("models.pull.downloading")}
                value={pull.fraction}
                indeterminate={pull.indeterminate && pull.active}
              />
            </div>
          )}
        </Section>

        <Section title={t("models.storage.title")} description={t("models.storage.description")}>
          <Row leading={<Tile icon="folder" />} title={t("models.storage.location")}>
            <Value>{storePath}</Value>
          </Row>
          <Row leading={<Tile icon="hard-drive" />} title={t("models.storage.usage")}>
            <Value mono={false}>
              {t("models.storage.usageValue", {
                size: humanBytes(totalBytes),
                models: tn("models.storage.modelsCount", models?.length ?? 0),
              })}
            </Value>
          </Row>
          <Row leading={<Tile icon="trash" />} title={t("models.storage.cleanup")} description={t("models.storage.cleanupHint")}>
            <Button size="sm" loading={pruning} onClick={() => void prune()}>
              {t("models.storage.cleanup")}
            </Button>
          </Row>
        </Section>
      </PageBody>

      <Modal
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={t("models.installed.removeTitle")}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRemoving(null)}>
              {t("common.cancel")}
            </Button>
            <Button variant="danger" onClick={() => removing && void remove(removing)}>
              {t("models.installed.remove")}
            </Button>
          </>
        }
      >
        <p className="text-[13px] text-muted-foreground">
          {t("models.installed.removeBody", { name: `${removing?.name}:${removing?.tag}` })}
        </p>
      </Modal>
    </>
  );
}

function RecRow({
  icon,
  title,
  value,
  reason,
  link,
  onUse,
  useLabel,
}: {
  icon: "mic" | "sparkles" | "eye";
  title: string;
  value: string;
  reason: string;
  link?: React.ReactNode;
  onUse: () => void;
  useLabel: string;
}) {
  return (
    <Row
      leading={<Tile icon={icon} />}
      title={
        <span className="flex items-center gap-2">
          {title}
          <span className="truncate font-mono text-[11.5px] font-normal text-accent-text">{value}</span>
        </span>
      }
      description={reason || undefined}
    >
      {link}
      <Button size="sm" onClick={onUse}>
        {useLabel}
      </Button>
    </Row>
  );
}
