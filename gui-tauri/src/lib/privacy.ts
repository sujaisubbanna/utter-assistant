import { useConfig } from "./config";

export type RemotePart = "llm" | "vision" | "stt";

const LOCAL_HOSTS = /^(localhost|127(?:\.\d{1,3}){3}|\[?::1\]?|0\.0\.0\.0)$/i;

/** True when a configured endpoint points somewhere other than this machine. */
export function isRemoteUrl(url: string): boolean {
  const value = url.trim();
  if (!value) return false;
  try {
    return !LOCAL_HOSTS.test(new URL(value).hostname);
  } catch {
    return false;
  }
}

/**
 * Which parts of the pipeline are configured to leave this computer. The
 * offline promise in the UI is derived from this, so it never over-claims.
 */
export function useRemoteParts(): RemotePart[] {
  const { get } = useConfig();
  const parts: RemotePart[] = [];
  if (
    String(get("router", "llm_provider", "vllm")) === "remote" ||
    isRemoteUrl(String(get("router", "llm_base_url", "")))
  )
    parts.push("llm");
  if (Boolean(get("vision", "enabled", true)) && isRemoteUrl(String(get("vision", "base_url", "")))) parts.push("vision");
  if (String(get("stt", "backend", "faster_whisper")) === "remote") parts.push("stt");
  return parts;
}

export const REMOTE_ROUTE: Record<RemotePart, string> = { llm: "llm", vision: "perception", stt: "voice" };
