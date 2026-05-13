import { motion } from "framer-motion";

type TurntableProps = {
  isPlaying: boolean;
};

export function Turntable({ isPlaying }: TurntableProps) {
  return (
    <div className="turntable relative flex min-h-[176px] flex-1 items-center justify-center overflow-hidden rounded-[14px] border border-white/10 p-3 shadow-control">
      <div className="absolute left-2 top-2 h-2 w-2 rounded-full border border-white/25 bg-black/40" />
      <div className="absolute bottom-2 left-2 h-2 w-2 rounded-full border border-white/25 bg-black/40" />
      <div className="absolute bottom-2 right-2 h-2 w-2 rounded-full border border-white/25 bg-black/40" />
      <div
        className={
          isPlaying
            ? "absolute bottom-5 left-4 h-1.5 w-1.5 rounded-full bg-[#76a7ff] shadow-[0_0_16px_rgba(118,167,255,0.8)]"
            : "absolute bottom-5 left-4 h-1.5 w-1.5 rounded-full bg-white/25"
        }
      />

      <motion.div
        className="vinyl"
        animate={isPlaying ? { rotate: 360 } : { rotate: 0 }}
        transition={
          isPlaying
            ? { repeat: Infinity, duration: 18, ease: "linear" }
            : { duration: 0.2 }
        }
      >
        <div className="vinyl-label">
          <span />
        </div>
      </motion.div>

      <div className="tone-arm" aria-hidden="true">
        <div className="arm-weight" />
        <div className="arm-line" />
        <div className="needle" />
      </div>

      <div className="absolute bottom-4 right-4 h-8 w-8 rounded-full border border-white/10 bg-gradient-to-br from-[#343432] to-[#111112] shadow-control" />
    </div>
  );
}
