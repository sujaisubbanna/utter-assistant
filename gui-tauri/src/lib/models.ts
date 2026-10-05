import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import { PULL_SOURCES } from "./links";
import type { ModelEntry, Recommendation } from "./types";

/**
 * A model a feature needs, resolved against the real model store and the
 * hardware recommendation. `source` is only set when the store can actually
 * pull the model (see `PULL_SOURCES`); speech models are fetched by the speech
 * engine itself, so they have no source and are not downloaded here.
 */
export type ModelKind = "stt" | "vision";

export interface ModelNeed {
  kind: ModelKind;
  /** The recommended model name for this computer. */
  model: string;
  /** Approximate download size in bytes, when known. */
  size?: number;
  /**
   * A source the model store can pull, when one exists. UI-TARS vision repos
   * are sharded safetensors with no single-file pull, so this is undefined for
   * them; callers must guard (see ModelRequired.tsx).
   */
  source?: string;
  installed: boolean;
  /** False when the hardware probe failed and this is a safe fallback. */
  estimated: boolean;
}

const GB = 1e9;

/** Used when `assistant recommend` can't be reached. */
const FALLBACK: Record<ModelKind, { model: string; size?: number; source?: string }> = {
  stt: { model: "ggml-small.en.bin", size: 466e6 },
  vision: { model: "UI-TARS-7B", size: 8e9 },
};

const DEFAULT_STORE = "~/.local/share/utter-models";

/** The distinguishing first word, e.g. "ui-tars" in "UI-TARS-1.5-7B". */
function leadingWord(value: string): string {
  const match = value.toLowerCase().match(/^[a-z]+(?:[-_.][a-z]+)?/);
  return match ? match[0] : value.toLowerCase();
}

/** Tolerant match so "UI-TARS-1.5-7B" counts as the recommended "UI-TARS-7B". */
export function isModelInstalled(models: ModelEntry[], model: string): boolean {
  const want = model.trim().toLowerCase();
  if (!want) return false;
  const lead = leadingWord(want);
  return models.some((entry) => {
    const name = String(entry.name ?? "").toLowerCase();
    if (!name) return false;
    if (name === want || name.includes(want) || want.includes(name)) return true;
    return lead.length >= 3 && leadingWord(name) === lead;
  });
}

/** The recommendation's memory estimate, in bytes. */
function estimateBytes(entry: Record<string, unknown> | undefined): number | undefined {
  const gb = Number(entry?.est_vram_gb ?? entry?.est_ram_gb);
  return Number.isFinite(gb) && gb > 0 ? Math.round(gb * GB) : undefined;
}

export interface ModelStatus {
  loading: boolean;
  storePath: string;
  models: ModelEntry[];
  recommendation: Recommendation | null;
  /** True when the hardware probe failed (the UI falls back to a default). */
  recFailed: boolean;
  refresh: () => Promise<void>;
  /** The need for a feature, or null when the feature needs no model. */
  need: (kind: ModelKind) => ModelNeed | null;
}

/** Read the real model store + hardware recommendation once, on mount. */
export function useModelStatus(): ModelStatus {
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [storePath, setStorePath] = useState(DEFAULT_STORE);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [recFailed, setRecFailed] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    const [list, rec, info] = await Promise.allSettled([
      api.modelsList(),
      api.recommend(),
      api.appInfo(),
    ]);
    if (list.status === "fulfilled") {
      setModels(list.value?.models ?? []);
      const root =
        list.value?.store?.root ?? (info.status === "fulfilled" ? info.value.models_path : "");
      if (root) setStorePath(root);
    } else {
      setModels([]);
    }
    if (rec.status === "fulfilled") {
      setRecommendation(rec.value);
      setRecFailed(false);
    } else {
      setRecommendation(null);
      setRecFailed(true);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const need = useCallback(
    (kind: ModelKind): ModelNeed | null => {
      if (loading) return null;
      const suggestions = recommendation?.suggestions;

      if (kind === "stt") {
        const stt = (suggestions?.stt ?? {}) as Record<string, unknown>;
        // Apple Speech needs no downloaded model.
        if (String(stt.backend ?? "") === "apple_speech") return null;
        const fallback = FALLBACK.stt;
        const hasRec = Boolean(stt.model);
        const model = String(stt.model || fallback.model);
        return {
          kind,
          model,
          size: hasRec ? estimateBytes(stt) : fallback.size,
          // The speech engine fetches its own models; nothing to pull here.
          installed: isModelInstalled(models, model),
          estimated: !hasRec,
        };
      }

      const vision = (suggestions?.vision ?? {}) as Record<string, unknown>;
      const fallback = FALLBACK.vision;
      const model = String(vision.model ?? "");
      // "none" means accessibility-only, so no model is required.
      if (recommendation && (!model || model === "none")) return null;
      const resolved = recommendation ? model : fallback.model;
      return {
        kind,
        model: resolved,
        size: recommendation ? estimateBytes(vision) : fallback.size,
        source: PULL_SOURCES[resolved] ?? fallback.source,
        installed: isModelInstalled(models, resolved),
        estimated: !recommendation,
      };
    },
    [loading, recommendation, models],
  );

  return { loading, storePath, models, recommendation, recFailed, refresh, need };
}
