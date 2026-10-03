import type { IconName } from "../components/icons";
import type { MessageKey } from "../i18n";

/**
 * The kind→icon fallback used wherever an app has no real icon (Linux desktop
 * entries and macOS bundles will not always yield one). Kept in one place so
 * the Apps page and the onboarding app picker never drift apart.
 */
export const KIND_ICON: Record<string, IconName> = {
  browser: "globe",
  editor: "terminal",
  media: "play",
  chat: "link",
  terminal: "terminal",
  game: "zap",
  filemanager: "folder",
};

export const KINDS = new Set(Object.keys(KIND_ICON));

export function kindLabelKey(kind: string): MessageKey {
  return `apps.kinds.${KINDS.has(kind) ? kind : "other"}` as MessageKey;
}
