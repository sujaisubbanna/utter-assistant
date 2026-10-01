/**
 * Map DOM `KeyboardEvent.code` values to Linux evdev key names (`KEY_F13` …).
 *
 * The config stores evdev names (see `[ptt]` in config.default.toml). `code`
 * is the *physical* key, which lines up with evdev far better than `key`.
 */

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const FKEYS = Array.from({ length: 24 }, (_, i) => `F${i + 1}`);

const MAP: Record<string, string> = {
  Escape: "KEY_ESC",
  Tab: "KEY_TAB",
  CapsLock: "KEY_CAPSLOCK",
  ShiftLeft: "KEY_LEFTSHIFT",
  ShiftRight: "KEY_RIGHTSHIFT",
  ControlLeft: "KEY_LEFTCTRL",
  ControlRight: "KEY_RIGHTCTRL",
  AltLeft: "KEY_LEFTALT",
  AltRight: "KEY_RIGHTALT",
  MetaLeft: "KEY_LEFTMETA",
  MetaRight: "KEY_RIGHTMETA",
  ContextMenu: "KEY_COMPOSE",
  Space: "KEY_SPACE",
  Enter: "KEY_ENTER",
  NumpadEnter: "KEY_KPENTER",
  Backspace: "KEY_BACKSPACE",
  Insert: "KEY_INSERT",
  Delete: "KEY_DELETE",
  Home: "KEY_HOME",
  End: "KEY_END",
  PageUp: "KEY_PAGEUP",
  PageDown: "KEY_PAGEDOWN",
  ArrowUp: "KEY_UP",
  ArrowDown: "KEY_DOWN",
  ArrowLeft: "KEY_LEFT",
  ArrowRight: "KEY_RIGHT",
  Minus: "KEY_MINUS",
  Equal: "KEY_EQUAL",
  BracketLeft: "KEY_LEFTBRACE",
  BracketRight: "KEY_RIGHTBRACE",
  Backslash: "KEY_BACKSLASH",
  Semicolon: "KEY_SEMICOLON",
  Quote: "KEY_APOSTROPHE",
  Comma: "KEY_COMMA",
  Period: "KEY_DOT",
  Slash: "KEY_SLASH",
  Backquote: "KEY_GRAVE",
  IntlBackslash: "KEY_102ND",
  IntlRo: "KEY_RO",
  IntlYen: "KEY_YEN",
  PrintScreen: "KEY_SYSRQ",
  ScrollLock: "KEY_SCROLLLOCK",
  Pause: "KEY_PAUSE",
  NumLock: "KEY_NUMLOCK",
  Numpad0: "KEY_KP0",
  Numpad1: "KEY_KP1",
  Numpad2: "KEY_KP2",
  Numpad3: "KEY_KP3",
  Numpad4: "KEY_KP4",
  Numpad5: "KEY_KP5",
  Numpad6: "KEY_KP6",
  Numpad7: "KEY_KP7",
  Numpad8: "KEY_KP8",
  Numpad9: "KEY_KP9",
  NumpadAdd: "KEY_KPPLUS",
  NumpadSubtract: "KEY_KPMINUS",
  NumpadMultiply: "KEY_KPASTERISK",
  NumpadDivide: "KEY_KPSLASH",
  NumpadDecimal: "KEY_KPDOT",
};

for (const letter of LETTERS) {
  MAP[`Key${letter}`] = `KEY_${letter}`;
}
for (let digit = 0; digit <= 9; digit += 1) {
  MAP[`Digit${digit}`] = `KEY_${digit}`;
}
for (const fkey of FKEYS) {
  MAP[fkey] = `KEY_${fkey}`;
}

const MODIFIERS = new Set([
  "KEY_LEFTSHIFT",
  "KEY_RIGHTSHIFT",
  "KEY_LEFTCTRL",
  "KEY_RIGHTCTRL",
  "KEY_LEFTALT",
  "KEY_RIGHTALT",
  "KEY_LEFTMETA",
  "KEY_RIGHTMETA",
  "KEY_CAPSLOCK",
  "KEY_NUMLOCK",
  "KEY_SCROLLLOCK",
  "KEY_COMPOSE",
]);

const PRETTY: Record<string, string> = {
  KEY_LEFTCTRL: "Left Ctrl",
  KEY_RIGHTCTRL: "Right Ctrl",
  KEY_LEFTSHIFT: "Left Shift",
  KEY_RIGHTSHIFT: "Right Shift",
  KEY_LEFTALT: "Left Alt",
  KEY_RIGHTALT: "Right Alt",
  KEY_LEFTMETA: "Left Super",
  KEY_RIGHTMETA: "Right Super",
  KEY_INSERT: "Insert",
  KEY_DELETE: "Delete",
  KEY_ENTER: "Enter",
  KEY_KPENTER: "Numpad Enter",
  KEY_SPACE: "Space",
  KEY_ESC: "Escape",
  KEY_TAB: "Tab",
  KEY_BACKSPACE: "Backspace",
  KEY_PAGEUP: "Page Up",
  KEY_PAGEDOWN: "Page Down",
  KEY_CAPSLOCK: "Caps Lock",
  KEY_COMPOSE: "Menu",
};

export function domCodeToEvdev(code: string): string | null {
  return MAP[code] ?? null;
}

export function isModifier(evdevName: string): boolean {
  return MODIFIERS.has(evdevName);
}

export function displayName(evdevName: string): string {
  if (!evdevName) return "not set";
  if (PRETTY[evdevName]) return PRETTY[evdevName];
  const pretty = evdevName.startsWith("KEY_") ? evdevName.slice(4) : evdevName;
  if (/^F\d+$/.test(pretty)) return pretty;
  return pretty.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}


// --------------------------------------------------------------------------- //
// macOS: the `[macos]` section stores Quartz key names (see utter/macos/hotkey.py)
// --------------------------------------------------------------------------- //
const MAC_MAP: Record<string, string> = {
  AltRight: "right_option",
  AltLeft: "left_option",
  MetaRight: "right_command",
  MetaLeft: "left_command",
  ControlRight: "right_control",
  ControlLeft: "left_control",
  ShiftRight: "right_shift",
  ShiftLeft: "left_shift",
  CapsLock: "caps_lock",
  Fn: "fn",
  Space: "space",
  Escape: "escape",
  Tab: "tab",
  Backquote: "grave",
  Home: "home",
  End: "end",
  PageUp: "page_up",
  PageDown: "page_down",
  Insert: "insert",
  Help: "help",
};
for (let n = 1; n <= 20; n += 1) {
  MAC_MAP[`F${n}`] = `f${n}`;
}

const MAC_MODIFIERS = new Set([
  "right_option", "left_option", "right_command", "left_command", "right_control",
  "left_control", "right_shift", "left_shift", "caps_lock", "fn",
]);

const MAC_PRETTY: Record<string, string> = {
  right_option: "Right ⌥ Option",
  left_option: "Left ⌥ Option",
  right_command: "Right ⌘ Command",
  left_command: "Left ⌘ Command",
  right_control: "Right ⌃ Control",
  left_control: "Left ⌃ Control",
  right_shift: "Right ⇧ Shift",
  left_shift: "Left ⇧ Shift",
  caps_lock: "⇪ Caps Lock",
  fn: "fn",
  space: "Space",
  escape: "Escape",
  tab: "Tab",
  grave: "`",
  page_up: "Page Up",
  page_down: "Page Down",
};

export function domCodeToMacKey(code: string): string | null {
  return MAC_MAP[code] ?? null;
}

export function isMacModifier(name: string): boolean {
  return MAC_MODIFIERS.has(name);
}

export function displayMacKey(name: string): string {
  if (!name) return "not set";
  if (MAC_PRETTY[name]) return MAC_PRETTY[name];
  if (/^f\d+$/.test(name)) return name.toUpperCase();
  return name.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}
