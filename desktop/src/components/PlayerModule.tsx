import type { PointerEvent } from "react";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Turntable } from "@/components/Turntable";
import type { Track } from "@/radioData";

type PlayerModuleProps = {
  currentTrack: Track;
  isLoading?: boolean;
  isPlaying: boolean;
  progress: number;
  onNext: () => void;
  onPlayPause: () => void;
  onPrevious: () => void;
  onSeek: (seconds: number) => void;
};

function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${minutes}:${rest.toString().padStart(2, "0")}`;
}

export function PlayerModule({
  currentTrack,
  isLoading = false,
  isPlaying,
  progress,
  onNext,
  onPlayPause,
  onPrevious,
  onSeek,
}: PlayerModuleProps) {
  const progressPercent = Math.min(100, (progress / currentTrack.duration) * 100);

  function handleSeek(event: PointerEvent<HTMLButtonElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    onSeek(Math.round(currentTrack.duration * ratio));
  }

  return (
    <section className="player-deck grid grid-cols-[1.08fr_1fr] gap-3 rounded-[18px] p-3">
      <Turntable isPlaying={isPlaying} />
      <div className="track-display flex min-w-0 flex-col rounded-[14px] px-4 py-3 text-panel">
        <p className="player-kicker text-[9px] font-semibold uppercase tracking-[0.08em]">
          {isLoading ? "Tuning" : "Now Playing"}
        </p>
        <div className="mt-3 min-w-0">
          <h2 className="player-title truncate text-[17px] font-medium leading-tight">
            {isLoading ? "..." : currentTrack.title}
          </h2>
          <p className="player-artist mt-1 truncate text-[13px]">
            {isLoading ? "..." : currentTrack.artist}
          </p>
        </div>

        <div className="mt-4">
          <button
            aria-label="Seek playback"
            className="block h-2 w-full rounded-full bg-white/10 text-left shadow-[inset_0_1px_2px_rgba(0,0,0,0.32)]"
            onPointerDown={handleSeek}
            type="button"
          >
            <motion.div
              className="h-full rounded-full bg-[#f5f3ee]"
              animate={{ width: `${progressPercent}%` }}
              transition={{ duration: 0.25, ease: "easeOut" }}
            />
          </button>
          <div className="player-time mt-2 flex justify-between text-[10px] tabular-nums">
            <span>{formatTime(progress)}</span>
            <span>{formatTime(currentTrack.duration)}</span>
          </div>
        </div>

        <div className="mt-auto flex items-center justify-center gap-3 pt-4">
          <Button
            aria-label="Previous"
            variant="primary"
            size="icon"
            className="transport-button h-10 w-10 border border-white/8 bg-[#19191b]"
            onClick={onPrevious}
          >
            <SkipBack className="h-4 w-4 fill-current" />
          </Button>
          <Button
            aria-label={isPlaying ? "Pause" : "Play"}
            variant="primary"
            size="icon"
            className="transport-button transport-button-main h-14 w-14 border border-white/14 bg-[#222225] shadow-[0_16px_30px_rgba(0,0,0,0.36),inset_0_1px_0_rgba(255,255,255,0.14),inset_0_-10px_20px_rgba(0,0,0,0.22)]"
            onClick={onPlayPause}
          >
            {isPlaying ? (
              <Pause className="h-6 w-6 fill-current" />
            ) : (
              <Play className="ml-0.5 h-6 w-6 fill-current" />
            )}
          </Button>
          <Button
            aria-label="Next"
            variant="primary"
            size="icon"
            className="transport-button h-10 w-10 border border-white/8 bg-[#19191b]"
            onClick={onNext}
          >
            <SkipForward className="h-4 w-4 fill-current" />
          </Button>
        </div>
      </div>
    </section>
  );
}
