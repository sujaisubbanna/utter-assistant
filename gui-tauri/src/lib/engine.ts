import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import { usePoll } from "./hooks";

/** The official one-liner, exactly as the project publishes it. */
export const INSTALL_ONE_LINER =
  "curl -fsSL https://utter.sujaisubbanna.com/install.sh | bash";

/**
 * Whether the `assistant` engine can run at all. `null` while the first check
 * is in flight. A GUI-only AppImage/deb/rpm ships no Python core, so this is
 * how the UI knows to offer the shell installer. While the engine is missing it
 * re-checks gently, so the card disappears on its own once the user installs it.
 */
export function useEnginePresent(): { present: boolean | null } {
  const [present, setPresent] = useState<boolean | null>(null);

  const check = useCallback(async () => {
    try {
      setPresent(await api.enginePresent());
    } catch {
      // No answer means the engine cannot run.
      setPresent(false);
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  usePoll(() => check(), 10000, present === false);

  return { present };
}
