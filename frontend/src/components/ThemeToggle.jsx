import { Sun, Moon } from "lucide-react";
import { useDarkMode } from "../context/DarkModeContext";

export default function ThemeToggle() {
  const { isDark, toggle } = useDarkMode();
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-foreground-muted transition hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
    >
      {isDark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}
