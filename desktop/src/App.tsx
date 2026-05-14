import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { chatStation, generateStation, loadConfig, saveConfig } from "@/api/desktopApi";
import type { ApiSettings, RuntimeStatus } from "@/api/types";
import { ChatPanel } from "@/components/ChatPanel";
import { ContextStrip } from "@/components/ContextStrip";
import { PlayerModule } from "@/components/PlayerModule";
import { ProgramCards } from "@/components/ProgramCards";
import { SettingsPanel } from "@/components/SettingsPanel";
import { WindowControls } from "@/components/WindowControls";
import { emptyStation, type ChatMessage, type Station } from "@/radioData";

type ThemeMode = "light" | "dark";

function formatClock(date: Date) {
  return new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatDate(date: Date) {
  return new Intl.DateTimeFormat("en", {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(date);
}

function makeMessage(role: ChatMessage["role"], text: string): ChatMessage {
  return {
    id: `${role}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    role,
    text,
    time: formatClock(new Date()),
  };
}

export function App() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const narrationRef = useRef<HTMLAudioElement | null>(null);
  const hasBootstrappedRef = useRef(false);
  const requestInFlightRef = useRef(false);
  const [theme, setTheme] = useState<ThemeMode>(() =>
    window.localStorage.getItem("clownfish-theme") === "dark" ? "dark" : "light",
  );
  const [stationList, setStationList] = useState<Station[]>([emptyStation]);
  const [activeStationId, setActiveStationId] = useState(emptyStation.id);
  const [trackIndex, setTrackIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [volume, setVolume] = useState(72);
  const [now, setNow] = useState(() => new Date());
  const [isAdapting, setIsAdapting] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [settings, setSettings] = useState<ApiSettings | null>(null);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [apiError, setApiError] = useState("");
  const [nativeNarrationText, setNativeNarrationText] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const station = useMemo(
    () =>
      stationList.find((item) => item.id === activeStationId) ??
      stationList[0] ??
      emptyStation,
    [activeStationId, stationList],
  );
  const currentTrack = station.tracks[trackIndex] ?? station.tracks[0] ?? emptyStation.tracks[0];
  const isStationReady = station.id !== emptyStation.id && station.tracks.length > 0;

  const applyRemoteStation = useCallback((remoteStation: Station, nextWarnings: string[]) => {
    setStationList((items) => {
      const withoutRemote = items.filter((item) => item.id !== remoteStation.id);
      return [remoteStation, ...withoutRemote].slice(0, 4);
    });
    setActiveStationId(remoteStation.id);
    setTrackIndex(0);
    setProgress(0);
    setIsPlaying(false);
    setNativeNarrationText(remoteStation.ttsAudioUrl ? "" : (remoteStation.greeting ?? remoteStation.agentLine));
    setWarnings(nextWarnings);
  }, []);

  const dismissNotice = useCallback((message: string) => {
    if (!message) {
      return;
    }
    setWarnings((items) => items.filter((item) => item !== message));
    setApiError((value) => (value === message ? "" : value));
  }, []);

  const requestAgentStation = useCallback(
    async (message: string) => {
      if (requestInFlightRef.current) {
        return;
      }
      requestInFlightRef.current = true;
      setIsAdapting(true);
      setApiError("");
      try {
        const response = await generateStation({
          city: settings?.weatherCity || station.city,
          message,
        });
        if (response?.station) {
          applyRemoteStation(response.station, response.warnings ?? []);
          setRuntime(response.runtime);
          const greeting = response.station.greeting || response.station.agentLine;
          setMessages((items) => [...items, makeMessage("agent", greeting)]);
        }
      } catch (error) {
        setApiError(error instanceof Error ? error.message : "Station generation failed");
      } finally {
        requestInFlightRef.current = false;
        setIsAdapting(false);
      }
    },
    [applyRemoteStation, settings?.weatherCity, station.city],
  );

  const nextTrack = useCallback(() => {
    setTrackIndex((index) => (index + 1) % station.tracks.length);
    setProgress(0);
    setIsPlaying(true);
  }, [station.tracks.length]);

  const previousTrack = useCallback(() => {
    setTrackIndex((index) => (index - 1 + station.tracks.length) % station.tracks.length);
    setProgress(0);
    setIsPlaying(true);
  }, [station.tracks.length]);

  const selectTrack = useCallback((index: number) => {
    setTrackIndex(index);
    setProgress(0);
    setIsPlaying(true);
    if (audioRef.current) {
      audioRef.current.currentTime = 0;
    }
  }, []);

  const seekTrack = useCallback((seconds: number) => {
    setProgress(seconds);
    if (audioRef.current) {
      audioRef.current.currentTime = seconds;
    }
  }, []);

  const handleSendMessage = useCallback(
    (text: string) => {
      const cleanText = text.trim();
      if (!cleanText || isAdapting || requestInFlightRef.current || !settings) {
        return;
      }
      requestInFlightRef.current = true;

      setMessages((items) => [...items, makeMessage("user", cleanText)]);

      setIsAdapting(true);
      setApiError("");
      chatStation({ city: settings.weatherCity || station.city, message: cleanText })
        .then((response) => {
          if (response?.station) {
            applyRemoteStation(response.station, response.warnings ?? []);
            setRuntime(response.runtime);
            const replyText =
              response.station.chatReply ||
              response.station.agentLine ||
              response.station.greeting ||
              "I retuned the station.";
            setMessages((items) => [
              ...items,
              makeMessage("agent", replyText),
            ]);
          }
        })
        .catch((error: unknown) => {
          setApiError(error instanceof Error ? error.message : "Chat request failed");
        })
        .finally(() => {
          requestInFlightRef.current = false;
          setIsAdapting(false);
        });
    },
    [applyRemoteStation, isAdapting, settings, station.city],
  );

  async function handleSaveSettings(nextSettings: ApiSettings) {
    const response = await saveConfig(nextSettings);
    setSettings(response.config);
    setRuntime(response.runtime);
    setIsSettingsOpen(false);
    await requestAgentStation("Generate a fresh station using the configured services.");
  }

  const toggleTheme = useCallback(() => {
    setTheme((value) => (value === "light" ? "dark" : "light"));
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("clownfish-theme", theme);
  }, [theme]);

  useEffect(() => {
    loadConfig()
      .then((response) => {
        setSettings(response.config);
        setRuntime(response.runtime);
      })
      .catch((error: unknown) => {
        setApiError(error instanceof Error ? error.message : "Failed to load settings");
      });
  }, []);

  useEffect(() => {
    if (!settings || hasBootstrappedRef.current) {
      return;
    }
    hasBootstrappedRef.current = true;
    requestAgentStation(
      "Open ClownfishStudio. Greet me using the current weather, time, and my listening context, then start a small personal radio set.",
    );
  }, [requestAgentStation, settings]);

  useEffect(() => {
    if (!isPlaying || currentTrack.playbackUrl) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      setProgress((value) => value + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [currentTrack.playbackUrl, isPlaying]);

  useEffect(() => {
    if (progress >= currentTrack.duration) {
      nextTrack();
    }
  }, [currentTrack.duration, nextTrack, progress]);

  useEffect(() => {
    audioRef.current?.pause();
    audioRef.current = null;

    if (!currentTrack.playbackUrl) {
      return undefined;
    }
    const audio = new Audio(currentTrack.playbackUrl);
    audioRef.current = audio;
    audio.volume = volume / 100;
    audio.preload = "auto";

    const syncProgress = () => setProgress(Math.round(audio.currentTime));
    const playNext = () => nextTrack();
    const handleError = () => {
      const mediaError = audio.error?.message || "unsupported source";
      setApiError(`Music playback failed for "${currentTrack.title}": ${mediaError}`);
      setIsPlaying(false);
    };
    audio.addEventListener("timeupdate", syncProgress);
    audio.addEventListener("ended", playNext);
    audio.addEventListener("error", handleError);

    return () => {
      audio.pause();
      audio.removeEventListener("timeupdate", syncProgress);
      audio.removeEventListener("ended", playNext);
      audio.removeEventListener("error", handleError);
      if (audioRef.current === audio) {
        audioRef.current = null;
      }
    };
  }, [currentTrack.playbackUrl, currentTrack.title, nextTrack]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !currentTrack.playbackUrl) {
      return;
    }

    if (isPlaying) {
      audio.play().catch((error: unknown) => {
        setApiError(error instanceof Error ? error.message : "Audio playback failed");
        setIsPlaying(false);
      });
    } else {
      audio.pause();
    }
  }, [currentTrack.playbackUrl, isPlaying]);

  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.volume = volume / 100;
    }
    if (narrationRef.current) {
      narrationRef.current.volume = Math.min(1, volume / 100 + 0.12);
    }
  }, [volume]);

  useEffect(() => {
    if (!station.ttsAudioUrl) {
      return undefined;
    }

    narrationRef.current?.pause();
    const narration = new Audio(station.ttsAudioUrl);
    narrationRef.current = narration;
    narration.volume = Math.min(1, volume / 100 + 0.12);
    const finishNarration = () => setIsPlaying(true);
    const failNarration = () => {
      setApiError("Narration playback failed");
      setIsPlaying(true);
    };
    narration.addEventListener("ended", finishNarration);
    narration.addEventListener("error", failNarration);
    narration.play().catch((error: unknown) => {
      setApiError(error instanceof Error ? error.message : "Narration playback failed");
      setIsPlaying(true);
    });

    return () => {
      narration.pause();
      narration.removeEventListener("ended", finishNarration);
      narration.removeEventListener("error", failNarration);
      if (narrationRef.current === narration) {
        narrationRef.current = null;
      }
    };
  }, [station.ttsAudioUrl]);

  useEffect(() => {
    if (!nativeNarrationText) {
      return undefined;
    }

    const speech = window.speechSynthesis;
    if (!speech || typeof SpeechSynthesisUtterance === "undefined") {
      setNativeNarrationText("");
      setIsPlaying(true);
      return undefined;
    }

    speech.cancel();
    const utterance = new SpeechSynthesisUtterance(nativeNarrationText);
    utterance.rate = 0.96;
    utterance.pitch = 0.95;
    utterance.volume = Math.min(1, volume / 100 + 0.12);
    utterance.lang = /[\u4e00-\u9fff]/.test(nativeNarrationText) ? "zh-CN" : "en-US";
    utterance.onend = () => {
      setNativeNarrationText("");
      setIsPlaying(true);
    };
    utterance.onerror = () => {
      setNativeNarrationText("");
      setIsPlaying(true);
    };
    speech.speak(utterance);

    return () => {
      speech.cancel();
    };
  }, [nativeNarrationText]);

  return (
    <main className="app-stage flex h-screen w-screen items-center justify-center overflow-hidden p-3 text-ink transition-colors duration-700">
      <motion.div
        className="device-shell flex h-[936px] w-[516px] flex-col overflow-hidden rounded-device border border-line/45 bg-shell p-4 shadow-device"
        initial={{ opacity: 0, scale: 0.985 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.45, ease: "easeOut" }}
      >
        <div className="app-surface flex min-h-0 flex-1 flex-col rounded-[24px] p-1 transition-colors duration-700">
          <header className="flex h-9 shrink-0 items-center justify-between rounded-t-[18px] px-2 [-webkit-app-region:drag]">
            <h1 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-ink">
              ClownfishStudio
            </h1>
            <WindowControls
              onOpenSettings={() => setIsSettingsOpen(true)}
              onToggleTheme={toggleTheme}
              theme={theme}
            />
          </header>

          <div className="min-h-0 flex-1 pb-1">
            <div className="grid h-full grid-rows-[auto_auto_auto_minmax(0,1fr)] gap-3">
              <PlayerModule
                currentTrack={currentTrack}
                isLoading={!isStationReady && isAdapting}
                isPlaying={isPlaying}
                progress={Math.min(progress, currentTrack.duration)}
                onNext={nextTrack}
                onPlayPause={() => setIsPlaying((value) => !value)}
                onPrevious={previousTrack}
                onSeek={seekTrack}
              />
              <ContextStrip
                city={station.city}
                condition={station.condition}
                dateLabel={formatDate(now)}
                temperature={station.temperature}
                timeLabel={formatClock(now)}
                volume={volume}
                weather={station.weather}
                onVolumeChange={setVolume}
              />
              <ProgramCards
                activeTrackIndex={trackIndex}
                isLoading={!isStationReady && isAdapting}
                tracks={station.tracks}
                onSelectTrack={selectTrack}
              />
              <ChatPanel
                apiError={apiError}
                isAdapting={isAdapting}
                isInitializing={!isStationReady && isAdapting}
                messages={messages}
                onDismissNotice={dismissNotice}
                onSendMessage={handleSendMessage}
                runtime={runtime}
                warnings={warnings}
              />
            </div>
          </div>
        </div>
      </motion.div>

      {settings ? (
        <SettingsPanel
          config={settings}
          onClose={() => setIsSettingsOpen(false)}
          onGenerate={() => requestAgentStation("Generate a fresh station.")}
          onSave={handleSaveSettings}
          open={isSettingsOpen}
          runtime={runtime}
        />
      ) : null}
    </main>
  );
}
