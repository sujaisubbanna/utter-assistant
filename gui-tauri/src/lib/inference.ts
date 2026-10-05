import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import type { InferenceStatus, ModelEntry, PlannerBackend } from "./types";

/**
 * The whisper.cpp speech model Utter requires on every platform. Speech is
 * mandatory, so the UI downloads this exact store source rather than trusting
 * the hardware probe (which omits a source on macOS or when it fails).
 */
export const REQUIRED_SPEECH_SOURCE = "hf:ggerganov/whisper.cpp:ggml-small.en.bin";

/** The store names a pull after the repo, not the file, so look for "whisper.cpp". */
export const REQUIRED_SPEECH_STORE = "whisper.cpp";

/** True when the required whisper.cpp model is present in the model store. */
export function speechInstalled(models: ModelEntry[] | null | undefined): boolean {
  return Boolean(
    models?.some(
      (model) => String(model.name ?? "").trim().toLowerCase() === REQUIRED_SPEECH_STORE,
    ),
  );
}

/**
 * Read the provisioning state of the sharded vision + planner models, and
 * whether the required whisper.cpp speech model is in the store.
 *
 * The vision/planner pair is installed outside the normal model store, so the
 * Models page can't see it with `models list`; `assistant inference status
 * --json` is the source of truth. A failed probe leaves `status` null (unknown),
 * which callers treat as "offer the download" rather than "ready". The speech
 * model is a normal store entry, so it is detected from `models list`.
 */
export function useInferenceStatus(): {
  status: InferenceStatus | null;
  /** True when the required whisper.cpp model is installed. */
  speech: boolean;
  loading: boolean;
  refresh: () => Promise<void>;
} {
  const [status, setStatus] = useState<InferenceStatus | null>(null);
  const [speech, setSpeech] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    const [probe, list] = await Promise.allSettled([api.inferenceStatus(), api.modelsList()]);
    setStatus(probe.status === "fulfilled" ? probe.value : null);
    setSpeech(list.status === "fulfilled" ? speechInstalled(list.value?.models) : false);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { status, speech, loading, refresh };
}

/** True only when both halves of the sharded set are present. */
export function inferenceReady(status: InferenceStatus | null): boolean {
  return Boolean(status?.vision && status?.planner);
}

/** Normalise the `planner_backend` field, tolerating aliases and bad values. */
export function normalizePlannerBackend(value: unknown): PlannerBackend | null {
  const raw = String(value ?? "").trim().toLowerCase();
  if (raw === "vllm") return "vllm";
  if (raw === "llamacpp" || raw === "llama.cpp" || raw === "llama_cpp") return "llamacpp";
  return null;
}

/**
 * The planner runtime a host uses when the engine doesn't report one. Linux
 * keeps vLLM + AWQ; macOS and Windows use llama.cpp + GGUF.
 */
export function defaultPlannerBackend(os: string): PlannerBackend {
  return os === "linux" ? "vllm" : "llamacpp";
}

/** The planner runtime to show: what the engine reports, else the platform default. */
export function plannerBackend(status: InferenceStatus | null, os: string): PlannerBackend {
  return normalizePlannerBackend(status?.planner_backend) ?? defaultPlannerBackend(os);
}

/** Brand name for a planner runtime (not translated — these are proper nouns). */
export function plannerBackendLabel(backend: PlannerBackend): string {
  return backend === "vllm" ? "vLLM" : "llama.cpp";
}

/** The planner checkpoint each runtime loads (short, human-readable form). */
export function plannerModelLabel(backend: PlannerBackend): string {
  return backend === "vllm"
    ? "Qwen3-4B-Instruct-2507 (AWQ 4-bit)"
    : "Qwen3-4B-Instruct-2507 (GGUF Q4_K_M)";
}
