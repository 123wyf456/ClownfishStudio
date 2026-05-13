import { useEffect, useState, type FormEvent } from "react";
import { RefreshCw, X } from "lucide-react";
import type { ApiSettings, RuntimeStatus } from "@/api/types";
import { Button } from "@/components/ui/button";

type SettingsPanelProps = {
  config: ApiSettings;
  onClose: () => void;
  onGenerate: () => void;
  onSave: (config: ApiSettings) => Promise<void>;
  open: boolean;
  runtime: RuntimeStatus | null;
};

export function SettingsPanel({
  config,
  onClose,
  onGenerate,
  onSave,
  open,
  runtime,
}: SettingsPanelProps) {
  const [draft, setDraft] = useState(config);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => setDraft(config), [config]);

  if (!open) {
    return null;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    try {
      await onSave(draft);
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/42 p-5 backdrop-blur-sm">
      <form
        className="screen-surface w-full max-w-[492px] rounded-[22px] border border-line/70 p-4 shadow-device"
        onSubmit={submit}
      >
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">API Settings</h2>
            <p className="text-[10px] text-muted">Keys are stored locally on this device.</p>
          </div>
          <Button aria-label="Close settings" size="icon" variant="ghost" onClick={onClose} type="button">
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="settings-scroll grid max-h-[730px] gap-3 overflow-y-auto pr-1">
          <section className="hardware-panel grid gap-2 rounded-[16px] border border-line/70 p-3">
            <SectionHeader label="Server" state="api" />
            <Field
              label="Base URL"
              value={draft.serverBaseUrl}
              onChange={(serverBaseUrl) => setDraft((value) => ({ ...value, serverBaseUrl }))}
            />
          </section>

          <section className="hardware-panel grid gap-2 rounded-[16px] border border-line/70 p-3">
            <SectionHeader label="Agent" state={runtime?.agent.mode ?? "mock"} />
            <label className="settings-label">
              Provider
              <select
                className="settings-input"
                onChange={(event) =>
                  setDraft((value) => ({
                    ...value,
                    agentProvider: event.target.value as ApiSettings["agentProvider"],
                  }))
                }
                value={draft.agentProvider}
              >
                <option value="mock">mock</option>
                <option value="deepseek">deepseek</option>
                <option value="openai">openai-compatible</option>
              </select>
            </label>
            <Field label="Model" value={draft.agentModel} onChange={(agentModel) => setDraft((value) => ({ ...value, agentModel }))} />
            <Field label="Base URL" value={draft.agentBaseUrl} onChange={(agentBaseUrl) => setDraft((value) => ({ ...value, agentBaseUrl }))} />
            <Field label="API Key" secret value={draft.agentApiKey} onChange={(agentApiKey) => setDraft((value) => ({ ...value, agentApiKey }))} />
          </section>

          <section className="hardware-panel grid gap-2 rounded-[16px] border border-line/70 p-3">
            <SectionHeader label="OpenWeather" state={runtime?.weather.mode ?? "mock"} />
            <Field label="City" value={draft.weatherCity} onChange={(weatherCity) => setDraft((value) => ({ ...value, weatherCity }))} />
            <Field label="Base URL" value={draft.openweatherBaseUrl} onChange={(openweatherBaseUrl) => setDraft((value) => ({ ...value, openweatherBaseUrl }))} />
            <Field label="API Key" secret value={draft.openweatherApiKey} onChange={(openweatherApiKey) => setDraft((value) => ({ ...value, openweatherApiKey }))} />
          </section>

          <section className="hardware-panel grid gap-2 rounded-[16px] border border-line/70 p-3">
            <SectionHeader label="NetEase Cloud Music" state={runtime?.music.mode ?? "mock"} />
            <Field label="API Base URL" value={draft.neteaseApiBaseUrl} onChange={(neteaseApiBaseUrl) => setDraft((value) => ({ ...value, neteaseApiBaseUrl }))} />
            <Field label="Playback Level" value={draft.neteasePlaybackLevel} onChange={(neteasePlaybackLevel) => setDraft((value) => ({ ...value, neteasePlaybackLevel }))} />
            <label className="settings-label">
              Cookie
              <textarea
                className="settings-input min-h-[68px] resize-none"
                onChange={(event) => setDraft((value) => ({ ...value, neteaseCookie: event.target.value }))}
                value={draft.neteaseCookie}
              />
            </label>
          </section>

          <section className="hardware-panel grid gap-2 rounded-[16px] border border-line/70 p-3">
            <SectionHeader label="Fish Audio" state={runtime?.tts.mode ?? "mock"} />
            <Field label="TTS URL" value={draft.fishAudioBaseUrl} onChange={(fishAudioBaseUrl) => setDraft((value) => ({ ...value, fishAudioBaseUrl }))} />
            <Field label="Voice ID" value={draft.fishAudioVoiceId} onChange={(fishAudioVoiceId) => setDraft((value) => ({ ...value, fishAudioVoiceId }))} />
            <Field label="API Key" secret value={draft.fishAudioApiKey} onChange={(fishAudioApiKey) => setDraft((value) => ({ ...value, fishAudioApiKey }))} />
          </section>
        </div>

        <div className="mt-4 flex items-center justify-between">
          <Button onClick={onGenerate} type="button" variant="soft">
            <RefreshCw className="mr-2 h-4 w-4" />
            Generate
          </Button>
          <div className="flex gap-2">
            <Button onClick={onClose} type="button" variant="ghost">
              Cancel
            </Button>
            <Button disabled={isSaving} type="submit" variant="primary">
              {isSaving ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}

function Field({
  label,
  onChange,
  secret,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  secret?: boolean;
  value: string;
}) {
  return (
    <label className="settings-label">
      {label}
      <input
        className="settings-input"
        onChange={(event) => onChange(event.target.value)}
        type={secret ? "password" : "text"}
        value={value}
      />
    </label>
  );
}

function SectionHeader({ label, state }: { label: string; state: string }) {
  return (
    <div className="flex items-center justify-between">
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
        {label}
      </p>
      <span className="rounded-full border border-line/70 bg-panel/70 px-2 py-0.5 text-[9px] text-muted">
        {state}
      </span>
    </div>
  );
}
