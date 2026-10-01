import { useEffect, useState, type ReactNode } from "react";

import { useConfig } from "../lib/config";
import { cn } from "../lib/utils";
import { splitList } from "../lib/format";
import { useDebouncedCallback } from "../lib/hooks";
import { Row } from "./ui/Row";
import { Switch } from "./ui/Switch";
import { Input } from "./ui/Input";
import { Select, type SelectOption } from "./ui/Select";
import { Button } from "./ui/Button";
import { useT } from "../i18n";

// --------------------------------------------------------------------------- //
// presentational
// --------------------------------------------------------------------------- //
export function SwitchSetting({
  title,
  description,
  checked,
  onChange,
  disabled,
  leading,
  extra,
}: {
  title: ReactNode;
  description?: ReactNode;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  leading?: ReactNode;
  extra?: ReactNode;
}) {
  return (
    <Row title={title} description={description} leading={leading}>
      {extra}
      <Switch checked={checked} onCheckedChange={onChange} disabled={disabled} ariaLabel={String(title)} />
    </Row>
  );
}

export function TextSetting({
  title,
  description,
  value,
  onSave,
  placeholder,
  type = "text",
  monospace,
  width = "w-60",
  disabled,
  leading,
}: {
  title: ReactNode;
  description?: ReactNode;
  value: string;
  onSave: (value: string) => void;
  placeholder?: string;
  type?: "text" | "password" | "url";
  monospace?: boolean;
  width?: string;
  disabled?: boolean;
  leading?: ReactNode;
}) {
  const t = useT();
  const [local, setLocal] = useState(value);
  useEffect(() => setLocal(value), [value]);
  const dirty = local !== value;
  const commit = () => {
    if (dirty) onSave(local);
  };

  return (
    <Row title={title} description={description} leading={leading}>
      <Input
        value={local}
        type={type}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(event) => setLocal(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            commit();
            event.currentTarget.blur();
          }
        }}
        onBlur={commit}
        aria-label={typeof title === "string" ? title : undefined}
        className={cn(width, monospace && "font-mono text-[12px]")}
      />
      {dirty && (
        <Button size="sm" variant="primary" onClick={commit} className="animate-pop">
          {t("common.save")}
        </Button>
      )}
    </Row>
  );
}

export function NumberSetting({
  title,
  description,
  value,
  onSave,
  min,
  max,
  step = 1,
  width = "w-28",
  disabled,
  suffix,
}: {
  title: ReactNode;
  description?: ReactNode;
  value: number;
  onSave: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  width?: string;
  disabled?: boolean;
  suffix?: string;
}) {
  const [local, setLocal] = useState(String(value));
  useEffect(() => setLocal(String(value)), [value]);
  const commit = () => {
    const parsed = Number(local);
    if (!Number.isNaN(parsed) && parsed !== value) onSave(parsed);
    else setLocal(String(value));
  };

  return (
    <Row title={title} description={description}>
      <div className="flex items-center gap-2">
        <Input
          type="number"
          value={local}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          onChange={(event) => setLocal(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              commit();
              event.currentTarget.blur();
            }
          }}
          aria-label={typeof title === "string" ? title : undefined}
          className={cn(width, "font-mono text-[12px]")}
        />
        {suffix && <span className="text-xs text-muted-foreground">{suffix}</span>}
      </div>
    </Row>
  );
}

export function SelectSetting({
  title,
  description,
  value,
  onChange,
  options,
  disabled,
  leading,
  extra,
}: {
  title: ReactNode;
  description?: ReactNode;
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  disabled?: boolean;
  leading?: ReactNode;
  extra?: ReactNode;
}) {
  return (
    <Row title={title} description={description} leading={leading}>
      {extra}
      <Select
        value={value}
        onChange={onChange}
        options={options}
        disabled={disabled}
        ariaLabel={String(title)}
        className="w-56"
      />
    </Row>
  );
}

export function RangeSetting({
  title,
  description,
  value,
  onChange,
  min,
  max,
  step,
  format,
}: {
  title: ReactNode;
  description?: ReactNode;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step: number;
  format?: (value: number) => string;
}) {
  return (
    <Row title={title} description={description}>
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
          className="range w-44 cursor-pointer"
          style={{ ["--fill" as string]: `${((value - min) / (max - min || 1)) * 100}%` }}
          aria-label={String(title)}
        />
        <span className="w-10 rounded-[5px] bg-wash py-0.5 text-center font-mono text-[11.5px] tabular-nums text-foreground">
          {format ? format(value) : value}
        </span>
      </div>
    </Row>
  );
}

// --------------------------------------------------------------------------- //
// config-bound: read + write ~/.config/utter/config.toml
// --------------------------------------------------------------------------- //
export function ConfigSwitch({
  section,
  k,
  title,
  description,
  fallback = false,
  disabled,
  extra,
}: {
  section: string;
  k: string;
  title: ReactNode;
  description?: ReactNode;
  fallback?: boolean;
  disabled?: boolean;
  extra?: ReactNode;
}) {
  const { get, set } = useConfig();
  return (
    <SwitchSetting
      title={title}
      description={description}
      checked={Boolean(get(section, k, fallback))}
      onChange={(next) => void set(section, k, next)}
      disabled={disabled}
      extra={extra}
    />
  );
}

export function ConfigText({
  section,
  k,
  title,
  description,
  fallback = "",
  placeholder,
  monospace,
  width,
}: {
  section: string;
  k: string;
  title: ReactNode;
  description?: ReactNode;
  fallback?: string;
  placeholder?: string;
  monospace?: boolean;
  width?: string;
}) {
  const { get, set } = useConfig();
  return (
    <TextSetting
      title={title}
      description={description}
      value={String(get(section, k, fallback))}
      onSave={(value) => void set(section, k, value)}
      placeholder={placeholder}
      monospace={monospace}
      width={width}
    />
  );
}

export function ConfigSelect({
  section,
  k,
  title,
  description,
  options,
  fallback,
}: {
  section: string;
  k: string;
  title: ReactNode;
  description?: ReactNode;
  options: SelectOption[];
  fallback: string;
}) {
  const { get, set } = useConfig();
  const value = String(get(section, k, fallback));
  const known = options.some((option) => option.value === value);
  return (
    <SelectSetting
      title={title}
      description={description}
      value={known ? value : fallback}
      options={options}
      onChange={(next) => void set(section, k, next)}
    />
  );
}

export function ConfigNumber({
  section,
  k,
  title,
  description,
  fallback,
  min,
  max,
  step,
  suffix,
  disabled,
}: {
  section: string;
  k: string;
  title: ReactNode;
  description?: ReactNode;
  fallback: number;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  disabled?: boolean;
}) {
  const { get, set } = useConfig();
  return (
    <NumberSetting
      title={title}
      description={description}
      value={Number(get(section, k, fallback))}
      onSave={(value) => void set(section, k, value)}
      min={min}
      max={max}
      step={step}
      suffix={suffix}
      disabled={disabled}
    />
  );
}

export function ConfigRange({
  section,
  k,
  title,
  description,
  fallback,
  min,
  max,
  step,
  format,
}: {
  section: string;
  k: string;
  title: ReactNode;
  description?: ReactNode;
  fallback: number;
  min: number;
  max: number;
  step: number;
  format?: (value: number) => string;
}) {
  const { get, set } = useConfig();
  const value = Number(get(section, k, fallback));
  // Local state keeps the thumb under the pointer while the save is debounced.
  const [local, setLocal] = useState(value);
  useEffect(() => setLocal(value), [value]);
  const save = useDebouncedCallback((next: number) => void set(section, k, next), 350);
  return (
    <RangeSetting
      title={title}
      description={description}
      value={local}
      onChange={(next) => {
        setLocal(next);
        save(next);
      }}
      min={min}
      max={max}
      step={step}
      format={format}
    />
  );
}

/** A comma-separated list stored as a TOML array (e.g. `require_confirm`). */
export function ConfigList({
  section,
  k,
  title,
  description,
  placeholder,
  fallback = [],
}: {
  section: string;
  k: string;
  title: ReactNode;
  description?: ReactNode;
  placeholder?: string;
  fallback?: string[];
}) {
  const { get, set } = useConfig();
  const raw = get<string[] | string>(section, k, fallback);
  const text = Array.isArray(raw) ? raw.join(", ") : String(raw ?? "");
  return (
    <TextSetting
      title={title}
      description={description}
      value={text}
      placeholder={placeholder ?? "comma, separated, values"}
      onSave={(value) => void set(section, k, splitList(value))}
      width="w-60"
    />
  );
}
