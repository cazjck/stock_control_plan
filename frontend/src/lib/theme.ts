import { useEffect, useState } from "react";

export type ThemePref = "auto" | "light" | "dark";
const KEY = "stockctl.theme";

function read(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "auto";
  } catch { return "auto"; }
}

export function applyTheme(pref: ThemePref) {
  const root = document.documentElement;
  if (pref === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", pref);
}

export function useTheme(): [ThemePref, (p: ThemePref) => void] {
  const [pref, setPref] = useState<ThemePref>(read);
  useEffect(() => {
    applyTheme(pref);
    try { pref === "auto" ? localStorage.removeItem(KEY) : localStorage.setItem(KEY, pref); } catch { /* bỏ qua */ }
  }, [pref]);
  return [pref, setPref];
}

/** Chuỗi đổi mỗi khi giao diện sáng/tối đổi (do người dùng chọn hoặc do hệ thống), để vẽ lại biểu đồ. */
export function useThemeKey(): string {
  const read = () =>
    `${document.documentElement.getAttribute("data-theme") ?? "auto"}:${window.matchMedia("(prefers-color-scheme: dark)").matches ? "d" : "l"}`;
  const [key, setKey] = useState(read);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setKey(read());
    mq.addEventListener("change", update);
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => { mq.removeEventListener("change", update); mo.disconnect(); };
  }, []);
  return key;
}

export const cssVar = (name: string): string => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
