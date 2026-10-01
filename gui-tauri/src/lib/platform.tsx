import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "./api";
import type { PlatformInfo } from "./types";

/**
 * Which desktop the settings app is running on. The backend answers from
 * `std::env::consts::OS`, so a Linux build never shows macOS screens and vice
 * versa. Until the answer arrives we assume Linux (the original target).
 */
const DEFAULT: PlatformInfo = { os: "linux", arch: "x86_64", macos: false, compositor: "unknown" };

interface PlatformApi extends PlatformInfo {
  isMac: boolean;
  ready: boolean;
  /** True only on a Wayland compositor Utter has a backend for (niri/KWin). */
  isWayland: boolean;
  /** niri/KWin expose no background key injection — app targeting is a round-trip. */
  isNiri: boolean;
  isKwin: boolean;
}

const PlatformContext = createContext<PlatformApi>({
  ...DEFAULT,
  isMac: false,
  ready: false,
  isWayland: false,
  isNiri: false,
  isKwin: false,
});

export function PlatformProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<PlatformInfo>(DEFAULT);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    api
      .platformInfo()
      .then((next) => setInfo(next))
      .catch(() => setInfo(DEFAULT))
      .finally(() => setReady(true));
  }, []);

  const value = useMemo<PlatformApi>(
    () => ({
      ...info,
      isMac: info.macos,
      ready,
      isWayland: info.os === "linux" && (info.compositor === "niri" || info.compositor === "kwin"),
      isNiri: info.compositor === "niri",
      isKwin: info.compositor === "kwin",
    }),
    [info, ready],
  );
  return <PlatformContext.Provider value={value}>{children}</PlatformContext.Provider>;
}

export function usePlatform(): PlatformApi {
  return useContext(PlatformContext);
}
