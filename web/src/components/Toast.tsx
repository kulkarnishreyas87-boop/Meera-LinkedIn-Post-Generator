import { AnimatePresence, motion } from "framer-motion";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Tone = "info" | "success" | "error";
interface ToastItem {
  id: number;
  text: string;
  tone: Tone;
}

const Ctx = createContext<(text: string, tone?: Tone) => void>(() => {});
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((text: string, tone: Tone = "info") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, text, tone }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), tone === "error" ? 7000 : 4200);
  }, []);

  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-20 z-50 flex flex-col items-center gap-2 px-4 lg:bottom-6" role="status" aria-live="polite">
        <AnimatePresence>
          {items.map((t) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: 12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 6 }}
              transition={{ duration: 0.22, ease: [0.2, 0.7, 0.2, 1] }}
              className={`pointer-events-auto flex max-w-md items-center gap-3 rounded-full border px-4 py-2.5 text-[13.5px] shadow-paper ${
                t.tone === "error"
                  ? "border-clay/40 bg-clay-soft text-ink"
                  : t.tone === "success"
                    ? "border-sage/40 bg-sage-soft text-ink"
                    : "border-hairline bg-card text-ink"
              }`}
            >
              <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${t.tone === "error" ? "bg-clay" : t.tone === "success" ? "bg-sage" : "bg-muted"}`} />
              {t.text}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </Ctx.Provider>
  );
}
