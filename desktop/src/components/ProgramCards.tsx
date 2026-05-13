import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { motion } from "framer-motion";
import type { Track } from "@/radioData";

type ProgramCardsProps = {
  activeTrackIndex: number;
  isLoading?: boolean;
  tracks: Track[];
  onSelectTrack: (trackIndex: number) => void;
};

export function ProgramCards({
  activeTrackIndex,
  isLoading = false,
  tracks,
  onSelectTrack,
}: ProgramCardsProps) {
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(tracks.length / 3));
  const visibleTracks = useMemo(
    () => (isLoading ? [] : tracks.slice(page * 3, page * 3 + 3)),
    [isLoading, page, tracks],
  );

  function scrollPrograms(direction: -1 | 1) {
    setPage((value) => (value + direction + pageCount) % pageCount);
  }

  useEffect(() => {
    const nextPage = Math.floor(activeTrackIndex / 3);
    setPage(Math.min(nextPage, pageCount - 1));
  }, [activeTrackIndex, pageCount]);

  useEffect(() => {
    setPage((value) => Math.min(value, pageCount - 1));
  }, [pageCount, tracks.length]);

  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-muted">
          Program
        </p>
        <div className="flex gap-1">
          <button
            aria-label="Previous songs"
            className="program-nav-button"
            onClick={() => scrollPrograms(-1)}
            type="button"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <button
            aria-label="Next songs"
            className="program-nav-button"
            onClick={() => scrollPrograms(1)}
            type="button"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div
        className="program-scroll grid grid-cols-3 gap-2 pb-1"
      >
        {isLoading
          ? Array.from({ length: 3 }).map((_, index) => (
              <div
                className="program-track-card program-track-card-loading rounded-[16px] border border-line/70 px-3 py-3 text-left"
                key={`loading-${index}`}
              >
                <span className="block h-3 w-16 rounded-full bg-muted/20" />
                <span className="mt-3 block h-2.5 w-11 rounded-full bg-muted/15" />
                <span className="mt-3 block h-2 w-8 rounded-full bg-muted/15" />
              </div>
            ))
          : visibleTracks.map((track, visibleIndex) => {
              const index = page * 3 + visibleIndex;
              return (
                <motion.button
                  key={track.id ?? `${track.title}-${index}`}
                  className={
                    index === activeTrackIndex
                      ? "program-track-card program-track-card-active snap-start rounded-[16px] border border-bluewash/80 px-3 py-3 text-left transition"
                      : "program-track-card snap-start rounded-[16px] border border-line/70 px-3 py-3 text-left transition"
                  }
                  onClick={() => onSelectTrack(index)}
                  transition={{ duration: 0.32, ease: "easeOut" }}
                  type="button"
                  whileHover={{ y: -2 }}
                  whileTap={{ y: 0, scale: 0.995 }}
                >
                  <span className="block truncate text-[12px] font-semibold leading-tight text-ink">
                    {track.title}
                  </span>
                  <span className="mt-2 block truncate text-[10px] text-muted">
                    {track.artist}
                  </span>
                  <span className="mt-2 block text-[9px] font-semibold tabular-nums text-muted/80">
                    {formatDuration(track.duration)}
                  </span>
                </motion.button>
              );
            })}
      </div>
    </section>
  );
}

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${minutes}:${rest.toString().padStart(2, "0")}`;
}
