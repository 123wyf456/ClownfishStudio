import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { ArrowUp, Bot, Mic, UserRound, X } from "lucide-react";
import { motion } from "framer-motion";
import type { RuntimeStatus } from "@/api/types";
import { Button } from "@/components/ui/button";
import type { ChatMessage } from "@/radioData";

type ChatPanelProps = {
  apiError: string;
  isAdapting: boolean;
  isInitializing?: boolean;
  messages: ChatMessage[];
  onSendMessage: (text: string) => void;
  onDismissNotice?: (message: string) => void;
  runtime: RuntimeStatus | null;
  warnings: string[];
};

export function ChatPanel({
  apiError,
  isAdapting,
  isInitializing = false,
  messages,
  onSendMessage,
  onDismissNotice,
  runtime,
  warnings,
}: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const [waitingIndex, setWaitingIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeWarnings = [apiError, ...warnings].filter(Boolean).slice(0, 2);
  const waitingPhrases = useMemo(
    () =>
      isInitializing
        ? ["电台正在初始化", "正在校准今夜的频道", "正在准备第一段开场"]
        : ["电台正在回应", "正在收拢你的偏好", "正在整理下一段节目"],
    [isInitializing],
  );
  const waitingText = waitingPhrases[waitingIndex % waitingPhrases.length];

  useEffect(() => {
    const scrollNode = scrollRef.current;
    if (!scrollNode) {
      return;
    }
    scrollNode.scrollTo({ top: scrollNode.scrollHeight, behavior: "smooth" });
  }, [messages.length, activeWarnings.length]);

  useEffect(() => {
    if (!isAdapting) {
      setWaitingIndex(0);
      return;
    }

    const timer = window.setInterval(() => {
      setWaitingIndex((value) => value + 1);
    }, 1800);
    return () => window.clearInterval(timer);
  }, [isAdapting]);

  function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isAdapting) {
      return;
    }
    const cleanDraft = draft.trim();
    if (!cleanDraft) {
      return;
    }

    onSendMessage(cleanDraft);
    setDraft("");
  }

  function handleVoiceCue() {
    if (isAdapting) {
      return;
    }
    setDraft("Make it warmer and a little brighter.");
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }

  return (
    <section className="chat-console flex h-full min-h-0 flex-col overflow-hidden rounded-[18px] border border-line/70 p-3 backdrop-blur">
      <div className="mb-2 flex items-center justify-between gap-2 px-1">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-full border border-line bg-panel/70">
            <Bot className="h-3.5 w-3.5 text-ink" />
          </div>
          <p className="text-[11px] font-semibold text-ink">ClownfishStudio</p>
        </div>
        <div className="flex gap-1 text-[8px] uppercase tracking-[0.06em] text-muted">
          <span>{runtime?.agent.mode ?? "mock"}</span>
          <span>/</span>
          <span>{runtime?.music.mode ?? "mock"}</span>
        </div>
      </div>

      <div
        className="chat-scroll min-h-0 flex-1 basis-0 space-y-3 overflow-y-auto pr-1"
        ref={scrollRef}
      >
        {messages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-3 flex w-14 justify-center gap-1">
                <span className="h-1.5 w-1.5 rounded-full bg-muted/45" />
                <span className="h-1.5 w-1.5 rounded-full bg-muted/35" />
                <span className="h-1.5 w-1.5 rounded-full bg-muted/25" />
              </div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted">
                {isInitializing ? "正在校准电台" : "电台暂时安静"}
              </p>
            </div>
          </div>
        ) : null}
        {messages.map((message, index) =>
          message.role === "agent" ? (
            <div className="flex items-start gap-2" key={message.id}>
              <BubbleIcon />
              <div className="max-w-[78%]">
                <motion.div
                  className="chat-bubble-ai rounded-[14px] border border-bluewash/60 px-3 py-2 text-[11px] leading-relaxed text-ink"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.03, duration: 0.3 }}
                >
                  {message.text}
                </motion.div>
                <p className="mt-1 px-2 text-[8px] text-muted">{message.time}</p>
              </div>
            </div>
          ) : (
            <div className="flex items-start justify-end gap-2" key={message.id}>
              <div className="max-w-[72%] text-right">
                <motion.div
                  className="chat-bubble-user rounded-[14px] border border-line/60 px-3 py-2 text-left text-[10px] leading-relaxed text-ink"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.03, duration: 0.3 }}
                >
                  {message.text}
                </motion.div>
                <p className="mt-1 px-2 text-[8px] text-muted">{message.time}</p>
              </div>
              <div className="flex h-7 w-7 items-center justify-center rounded-full border border-line bg-panel/78">
                <UserRound className="h-3.5 w-3.5 text-ink" />
              </div>
            </div>
          ),
        )}
      </div>

      {activeWarnings.length > 0 ? (
        <div className="warning-panel mt-2 rounded-[12px] border px-3 py-2 text-[9px] leading-relaxed">
          <div className="flex items-start justify-between gap-2">
            <p className="min-w-0 flex-1">{activeWarnings.join(" ")}</p>
            {onDismissNotice ? (
              <button
                aria-label="Close notice"
                className="mt-[1px] shrink-0 rounded-full p-0.5 text-current/70 transition hover:bg-current/10 hover:text-current"
                onClick={() => onDismissNotice(activeWarnings[0])}
                type="button"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {isAdapting ? (
        <div className="mt-2 flex items-center gap-2 pl-10">
          <div className="flex items-center gap-1.5" aria-hidden="true">
            {[0, 1, 2].map((index) => (
              <motion.span
                animate={{ opacity: [0.25, 1, 0.25], y: [0, -1.5, 0] }}
                className="h-1.5 w-1.5 rounded-full bg-[#7f9ef4]"
                key={index}
                transition={{
                  duration: 1.15,
                  ease: "easeInOut",
                  repeat: Number.POSITIVE_INFINITY,
                  delay: index * 0.15,
                }}
              />
            ))}
          </div>
          <span className="text-[8px] text-muted">{waitingText}</span>
        </div>
      ) : null}

      <form
        className="voice-terminal mt-2 flex items-center gap-2 rounded-full border border-line/70 px-4 py-2"
        onSubmit={submitMessage}
      >
        <input
          aria-label="Ask ClownfishStudio"
          className="min-w-0 flex-1 bg-transparent text-[11px] text-ink outline-none placeholder:text-muted/75"
          disabled={isAdapting}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={isAdapting ? "电台正在回应..." : "和电台说说现在想听什么"}
          ref={inputRef}
          value={draft}
        />
        <Button
          aria-label="Voice input"
          size="icon"
          variant="ghost"
          className="h-8 w-8 bg-panel/70"
          disabled={isAdapting}
          onClick={handleVoiceCue}
          type="button"
        >
          <Mic className="h-4 w-4" />
        </Button>
        <Button
          aria-label="Send"
          size="icon"
          variant="primary"
          className="send-button h-8 w-8"
          disabled={isAdapting || !draft.trim()}
          type="submit"
        >
          <ArrowUp className="h-4 w-4" />
        </Button>
      </form>
    </section>
  );
}

function BubbleIcon() {
  return (
    <div className="mt-1 flex h-7 w-7 items-center justify-center rounded-full border border-bluewash/70 bg-bluewash/70">
      <Bot className="h-3.5 w-3.5 text-ink/72" />
    </div>
  );
}
