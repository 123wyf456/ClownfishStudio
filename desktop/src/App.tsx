import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { advancePlayer, chatStation, generateStation, loadConfig, saveConfig } from "@/api/desktopApi";
import { defaultSettings, type ApiSettings, type PlayerAdvanceReason, type RuntimeStatus } from "@/api/types";
import { ChatPanel } from "@/components/ChatPanel";
import { ContextStrip } from "@/components/ContextStrip";
import { PlayerModule } from "@/components/PlayerModule";
import { SettingsPanel } from "@/components/SettingsPanel";
import { WindowControls } from "@/components/WindowControls";
import { emptyStation, type ChatMessage, type Station } from "@/radioData";

type ThemeMode = "light" | "dark";
type ConfigLoadState = "loading" | "ready" | "failed";

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

function toUserFacingError(error: unknown, fallback: string): string {
  if (!(error instanceof Error)) {
    return fallback;
  }

  const message = error.message.trim();
  if (!message) {
    return fallback;
  }

  if (/[\u4e00-\u9fff]/.test(message)) {
    return message;
  }

  if (message.includes("422")) {
    return "这次请求没有找到可用结果，请调整描述后再试。";
  }
  if (message.includes("404")) {
    return "没有找到对应的服务接口。";
  }
  if (message.includes("502") || message.includes("503") || message.includes("504")) {
    return "电台服务暂时不可用，请稍后再试。";
  }

  return fallback;
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error(message)), timeoutMs);
    promise
      .then(resolve)
      .catch(reject)
      .finally(() => window.clearTimeout(timer));
  });
}

export function App() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const hasBootstrappedRef = useRef(false);
  const requestInFlightRef = useRef(false);
  const playbackAdvanceInFlightRef = useRef(false);
  const isMac = Boolean(window.clownfishRuntime?.isMac);
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
  const [settings, setSettings] = useState<ApiSettings>(defaultSettings);
  const [configLoadState, setConfigLoadState] = useState<ConfigLoadState>("loading");
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [apiError, setApiError] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [deviceLocation, setDeviceLocation] = useState<{
    latitude?: number;
    longitude?: number;
    cityHint?: string;
  } | null>(null);
  const [locationStatus, setLocationStatus] = useState<"idle" | "locating" | "ready" | "fallback">(
    "idle",
  );

  const station = useMemo(
    () =>
      stationList.find((item) => item.id === activeStationId) ??
      stationList[0] ??
      emptyStation,
    [activeStationId, stationList],
  );
  const currentTrack = station.tracks[trackIndex] ?? station.tracks[0] ?? emptyStation.tracks[0];
  const isStationReady = station.id !== emptyStation.id && station.tracks.length > 0;

  const applyRemoteStation = useCallback((remoteStation: Station, nextWarnings: string[], options?: {
    preservePlayback?: boolean;
    playAfterApply?: boolean;
  }) => {
    setStationList((items) => {
      const withoutRemote = items.filter((item) => item.id !== remoteStation.id);
      return [remoteStation, ...withoutRemote].slice(0, 4);
    });
    setActiveStationId(remoteStation.id);
    setTrackIndex(
      Math.max(
        0,
        Math.min(remoteStation.currentTrackIndex ?? 0, Math.max(0, remoteStation.tracks.length - 1)),
      ),
    );
    if (!options?.preservePlayback) {
      setProgress(0);
      setIsPlaying(Boolean(options?.playAfterApply));
    }
    setWarnings(nextWarnings.filter(Boolean));
    setApiError("");
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
          deviceLocation,
          message,
        });
        if (response?.station) {
          applyRemoteStation(response.station, response.warnings ?? []);
          setRuntime(response.runtime);
          const greeting = response.station.greeting || response.station.agentLine;
          setMessages((items) => [...items, makeMessage("agent", greeting)]);
        }
      } catch (error) {
        setApiError(toUserFacingError(error, "电台生成失败，请稍后再试。"));
      } finally {
        requestInFlightRef.current = false;
        setIsAdapting(false);
      }
    },
    [applyRemoteStation, deviceLocation],
  );

  const advancePlayback = useCallback(
    async (reason: PlayerAdvanceReason) => {
      if (!isStationReady || playbackAdvanceInFlightRef.current) {
        return;
      }
      playbackAdvanceInFlightRef.current = true;
      setApiError("");
      try {
        const response = await advancePlayer({
          itemId: currentTrack.id,
          reason,
        });
        if (response?.station) {
          applyRemoteStation(response.station, response.warnings ?? [], { playAfterApply: true });
          setRuntime(response.runtime);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : "";
        if (!message.includes("interrupted by a call to pause")) {
          setApiError(toUserFacingError(error, "播放切换失败，请稍后再试。"));
        }
        setIsPlaying(false);
      } finally {
        playbackAdvanceInFlightRef.current = false;
      }
    },
    [applyRemoteStation, currentTrack.id, isStationReady],
  );

  const nextTrack = useCallback(() => {
    void advancePlayback("next");
  }, [advancePlayback]);

  const previousTrack = useCallback(() => {
    void advancePlayback("previous");
  }, [advancePlayback]);

  const seekTrack = useCallback((seconds: number) => {
    setProgress(seconds);
    if (audioRef.current) {
      audioRef.current.currentTime = seconds;
    }
  }, []);

  const handleSendMessage = useCallback(
    (text: string) => {
      const cleanText = text.trim();
      if (!cleanText || isAdapting || requestInFlightRef.current || configLoadState !== "ready") {
        return;
      }
      requestInFlightRef.current = true;

      setMessages((items) => [...items, makeMessage("user", cleanText)]);

      setIsAdapting(true);
      setApiError("");
      chatStation({ deviceLocation, message: cleanText })
        .then((response) => {
          if (response?.station) {
            applyRemoteStation(response.station, response.warnings ?? [], { preservePlayback: true });
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
          setApiError(toUserFacingError(error, "聊天请求失败，请稍后再试。"));
        })
        .finally(() => {
          requestInFlightRef.current = false;
          setIsAdapting(false);
        });
    },
    [applyRemoteStation, configLoadState, deviceLocation, isAdapting],
  );

  async function handleSaveSettings(nextSettings: ApiSettings) {
    setApiError("");
    try {
      const response = await saveConfig(nextSettings);
      setSettings(response.config);
      setRuntime(response.runtime);
      setConfigLoadState("ready");
      setIsSettingsOpen(false);
    } catch (error) {
      setConfigLoadState("failed");
      setApiError(toUserFacingError(error, "保存配置失败，请确认后端已启动后再试。"));
      throw error;
    }
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
    withTimeout(loadConfig(), 35_000, "读取配置超时")
      .then((response) => {
        setSettings(response.config);
        setRuntime(response.runtime);
        setConfigLoadState("ready");
      })
      .catch((error: unknown) => {
        setConfigLoadState("failed");
        setApiError(toUserFacingError(error, "读取配置失败，请稍后再试。"));
      });
  }, []);

  useEffect(() => {
    if (!window.navigator?.geolocation) {
      setLocationStatus("fallback");
      return;
    }

    setLocationStatus("locating");
    const fallbackTimer = window.setTimeout(() => {
      setLocationStatus((value) => (value === "ready" ? value : "fallback"));
    }, 8_000);

    window.navigator.geolocation.getCurrentPosition(
      async (position) => {
        const latitude = position.coords.latitude;
        const longitude = position.coords.longitude;
        setDeviceLocation({ latitude, longitude });
        setLocationStatus("ready");
        window.clearTimeout(fallbackTimer);
      },
      () => {
        setLocationStatus("fallback");
        window.clearTimeout(fallbackTimer);
      },
      { enableHighAccuracy: false, timeout: 7_000, maximumAge: 10 * 60 * 1000 },
    );

    return () => window.clearTimeout(fallbackTimer);
  }, []);

  useEffect(() => {
    if (
      configLoadState !== "ready" ||
      hasBootstrappedRef.current ||
      locationStatus === "idle" ||
      locationStatus === "locating"
    ) {
      return;
    }
    hasBootstrappedRef.current = true;
    requestAgentStation(
      "启动 ClownfishStudio。简单打招呼并自我介绍，然后开始此刻的电台。",
    );
  }, [configLoadState, locationStatus, requestAgentStation]);

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
      void advancePlayback("ended");
    }
  }, [advancePlayback, currentTrack.duration, progress]);

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
    const playNext = () => {
      void advancePlayback("ended");
    };
    const handleError = () => {
      const mediaError = audio.error?.message || "unsupported source";
      if (!mediaError.includes("interrupted by a call to pause")) {
        setApiError(`播放 "${currentTrack.title}" 失败：${mediaError}`);
      }
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
  }, [advancePlayback, currentTrack.playbackUrl, currentTrack.title]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !currentTrack.playbackUrl) {
      return;
    }

    if (isPlaying) {
      audio.play().catch((error: unknown) => {
        const message = error instanceof Error ? error.message : "";
        if (!message.includes("interrupted by a call to pause")) {
          setApiError(toUserFacingError(error, "音频播放失败。"));
        }
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
  }, [volume]);

  return (
    <main className="app-stage flex h-screen w-screen items-center justify-center overflow-hidden p-3 text-ink transition-colors duration-700">
      <motion.div
        className="device-shell flex h-[936px] w-[516px] flex-col overflow-hidden rounded-device border border-line/45 bg-shell p-4 shadow-device"
        initial={{ opacity: 0, scale: 0.985 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.45, ease: "easeOut" }}
      >
        <div className="app-surface flex min-h-0 flex-1 flex-col rounded-[24px] p-1 transition-colors duration-700">
          <header className={`flex h-9 shrink-0 items-center justify-between rounded-t-[18px] px-2 [-webkit-app-region:drag] ${isMac ? "pl-16" : ""}`}>
            <h1 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-ink">
              ClownfishStudio
            </h1>
            <WindowControls
              onOpenSettings={() => setIsSettingsOpen(true)}
              onToggleTheme={toggleTheme}
              isMac={isMac}
              theme={theme}
            />
          </header>

          <div className="min-h-0 flex-1 pb-1">
            <div className="grid h-full grid-rows-[auto_auto_minmax(0,1fr)] gap-3">
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

      <SettingsPanel
        config={settings}
        configLoadState={configLoadState}
        onClose={() => setIsSettingsOpen(false)}
        onGenerate={() => requestAgentStation("Generate a fresh station.")}
        onSave={handleSaveSettings}
        open={isSettingsOpen}
        runtime={runtime}
      />
    </main>
  );
}
