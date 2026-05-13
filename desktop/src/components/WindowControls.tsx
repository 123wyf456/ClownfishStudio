import { Minus, Moon, Settings, SunMedium, X } from "lucide-react";
import { Button } from "@/components/ui/button";

type WindowControlsProps = {
  onOpenSettings: () => void;
  onToggleTheme: () => void;
  theme: "light" | "dark";
};

export function WindowControls({
  onOpenSettings,
  onToggleTheme,
  theme,
}: WindowControlsProps) {
  return (
    <div className="flex items-center gap-1 [-webkit-app-region:no-drag]">
      <Button
        aria-label="Toggle theme"
        size="icon"
        variant="ghost"
        className="theme-toggle h-7 w-7"
        onClick={onToggleTheme}
      >
        {theme === "dark" ? (
          <SunMedium className="h-3.5 w-3.5" />
        ) : (
          <Moon className="h-3.5 w-3.5" />
        )}
      </Button>
      <Button
        aria-label="Settings"
        size="icon"
        variant="ghost"
        className="h-7 w-7"
        onClick={onOpenSettings}
      >
        <Settings className="h-3.5 w-3.5" />
      </Button>
      <Button
        aria-label="Minimize"
        size="icon"
        variant="ghost"
        className="h-7 w-7"
        onClick={() => window.clownfishWindow?.minimize()}
      >
        <Minus className="h-3.5 w-3.5" />
      </Button>
      <Button
        aria-label="Close"
        size="icon"
        variant="ghost"
        className="h-7 w-7"
        onClick={() => window.clownfishWindow?.close()}
      >
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
