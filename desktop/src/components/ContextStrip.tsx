import { useEffect, useRef, type CSSProperties, type PointerEvent } from "react";
import { SunMedium } from "lucide-react";

type ContextStripProps = {
  city: string;
  condition: string;
  dateLabel: string;
  temperature: number;
  timeLabel: string;
  volume: number;
  weather: string;
  onVolumeChange: (volume: number) => void;
};

function clampVolume(value: number) {
  return Math.min(100, Math.max(0, Math.round(value)));
}

export function ContextStrip({
  city,
  condition,
  dateLabel,
  temperature,
  timeLabel,
  volume,
  weather,
  onVolumeChange,
}: ContextStripProps) {
  const volumeRef = useRef(volume);

  useEffect(() => {
    volumeRef.current = volume;
  }, [volume]);

  function commitVolume(nextVolume: number) {
    const cleanVolume = clampVolume(nextVolume);
    volumeRef.current = cleanVolume;
    onVolumeChange(cleanVolume);
  }

  function handleKnobPointerDown(event: PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handleKnobPointerMove(event: PointerEvent<HTMLButtonElement>) {
    if (event.buttons !== 1) {
      return;
    }
    commitVolume(volumeRef.current + event.movementX - event.movementY);
  }

  return (
    <section className="hardware-panel grid grid-cols-[1fr_1fr_1fr_96px] items-center rounded-[18px] border border-line/70 px-4 py-3">
      <div className="flex items-center gap-3 border-r border-line/60 pr-4">
        <div className="temperature-orb flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-line/70 bg-panel/70 shadow-[inset_0_1px_0_rgba(255,255,255,0.46)]">
          <SunMedium className="h-5 w-5 text-ink" strokeWidth={1.6} />
        </div>
        <div>
          <p className="text-[18px] font-semibold tabular-nums text-ink">{temperature}°C</p>
          <p className="text-[11px] text-muted">{weather}</p>
        </div>
      </div>
      <div className="border-r border-line/60 px-4">
        <p className="text-[14px] font-semibold text-ink">{city}</p>
        <p className="mt-1 text-[11px] text-muted">{condition}</p>
      </div>
      <div className="px-4">
        <p className="text-[14px] font-semibold tabular-nums text-ink">
          {timeLabel}
        </p>
        <p className="mt-1 text-[11px] text-muted">{dateLabel}</p>
      </div>
      <div className="flex flex-col items-center">
        <p className="mb-1 text-[8px] font-bold uppercase tracking-[0.06em] text-muted">
          Volume
        </p>
        <button
          aria-label="Volume knob"
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={volume}
          className="volume-knob"
          onPointerDown={handleKnobPointerDown}
          onPointerMove={handleKnobPointerMove}
          onWheel={(event) => {
            event.preventDefault();
            commitVolume(volumeRef.current - event.deltaY / 8);
          }}
          role="slider"
          style={
            {
              "--volume-turn": `${-135 + volume * 2.7}deg`,
            } as CSSProperties
          }
          type="button"
        />
        <div className="mt-1 flex w-full items-center justify-between px-1 text-[12px] font-semibold text-muted">
          <button
            className="rounded-full px-2 transition hover:bg-ink/5"
            onClick={() => commitVolume(volumeRef.current - 8)}
            type="button"
          >
            -
          </button>
          <span className="w-7 text-center text-[10px] tabular-nums">{volume}</span>
          <button
            className="rounded-full px-2 transition hover:bg-ink/5"
            onClick={() => commitVolume(volumeRef.current + 8)}
            type="button"
          >
            +
          </button>
        </div>
      </div>
    </section>
  );
}
