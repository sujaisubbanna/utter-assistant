import { useT } from "../i18n";
import { navFor } from "../lib/nav";
import { usePlatform } from "../lib/platform";
import { cn } from "../lib/utils";
import { Icon, type IconName } from "./icons";
import { Logo } from "./Logo";
import { ThemeControl } from "./ThemeControl";

function NavButton({
  active,
  label,
  icon,
  onClick,
  trailing,
}: {
  active: boolean;
  label: string;
  icon: IconName | "logo";
  onClick: () => void;
  trailing?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-current={active ? "page" : undefined}
      title={label}
      onClick={onClick}
      className={cn(
        "focus-ring group relative flex h-8 w-full items-center gap-2.5 rounded-md px-2.5 text-[13px] transition-[background-color,color,box-shadow] duration-150 ease-out max-[879px]:justify-center max-[879px]:px-0",
        active
          ? "bg-panel font-medium text-foreground shadow-raised"
          : "text-muted-foreground hover:bg-wash hover:text-foreground",
      )}
    >
      {icon === "logo" ? (
        <Logo size={15} className={cn("shrink-0", active ? "text-primary" : "text-current")} />
      ) : (
        <Icon
          name={icon}
          size={16}
          className={cn(
            "shrink-0 transition-colors duration-150",
            active ? "text-primary" : "text-muted-foreground/85 group-hover:text-foreground",
          )}
        />
      )}
      <span className="truncate max-[879px]:hidden">{label}</span>
      {trailing && <span className="ml-auto max-[879px]:hidden">{trailing}</span>}
    </button>
  );
}

export function Sidebar({
  active,
  onNavigate,
  version,
}: {
  active: string;
  onNavigate: (id: string) => void;
  version: string;
}) {
  const t = useT();
  const { isMac } = usePlatform();
  const groups = navFor(isMac);
  return (
    <aside className="flex w-[224px] shrink-0 flex-col bg-chrome max-[879px]:w-[60px]">
      <nav className="flex-1 overflow-y-auto px-3 pb-3 pt-1 max-[879px]:px-2" aria-label={t("nav.sections")}>
        {groups.map((group, index) => (
          <div key={group.labelKey} className={cn(index > 0 && "mt-5")}>
            <div className="eyebrow px-2.5 pb-1.5 max-[879px]:sr-only">{t(group.labelKey)}</div>
            <div className="space-y-px">
              {group.items.map((item) => (
                <NavButton
                  key={item.id}
                  active={item.id === active}
                  label={t(item.labelKey)}
                  icon={item.icon}
                  onClick={() => onNavigate(item.id)}
                />
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="space-y-2 px-3 pb-3 max-[879px]:px-2">
        <div className="max-[879px]:hidden">
          <ThemeControl compact stretch />
        </div>
        <div className="hidden justify-center max-[879px]:flex">
          <ThemeControl compact className="flex-col" />
        </div>
        <NavButton
          active={active === "about"}
          label={t("nav.about")}
          icon="logo"
          onClick={() => onNavigate("about")}
          trailing={<span className="font-mono text-[10.5px] text-muted-foreground/80">v{version}</span>}
        />
      </div>
    </aside>
  );
}
