import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "./api";
import type { PlatformInfo } from "./types";

/**
 * Which desktop the settings app is running on. The backend answers from
 * `std::env::consts::OS`, so a Linux build never shows macOS screens and vice
 * versa. Until the answer arrives we assume Linux (the original target).
 */
const DEFAULT: PlatformInfo = { os: "linux", arch: "x86_64", macos: false };

interface PlatformApi extends PlatformInfo {
  isMac: boolean;
  ready: boolean;
}

const PlatformContext = createContext<PlatformApi>({ ...DEFAULT, isMac: false, ready: false });

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

  const value = useMemo<PlatformApi>(() => ({ ...info, isMac: info.macos, ready }), [info, ready]);
  return <PlatformContext.Provider value={value}>{children}</PlatformContext.Provider>;
}

export function usePlatform(): PlatformApi {
  return useContext(PlatformContext);
}
