"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export interface StripSection {
  id: string;
  label: string;
}

/** Height of the sticky header plus this strip, so a section scrolled to lands just under them. */
const STICKY_OFFSET_PX = 120;

/**
 * The sticky chip strip (after Tabble's category strip): a table of contents that jumps, not a
 * filter that hides. The lit chip follows the section being read (scroll-spy), and keeps itself
 * in view inside its own strip. Sections are elements with `id` = `section.id`.
 */
export function SectionStrip({ sections, label }: { sections: StripSection[]; label: string }) {
  const [active, setActive] = useState<string | null>(sections[0]?.id ?? null);
  const strip = useRef<HTMLDivElement>(null);

  // Scroll-spy: the lit chip is the last section whose top has passed under the sticky bars.
  useEffect(() => {
    if (sections.length < 2) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      let current = sections[0].id;
      for (const s of sections) {
        const el = document.getElementById(s.id);
        if (el && el.getBoundingClientRect().top <= STICKY_OFFSET_PX + 8) current = s.id;
      }
      // At the very bottom a short last section can never reach the top: light it anyway.
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) current = sections[sections.length - 1].id;
      setActive(current);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    update();
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [sections]);

  useEffect(() => {
    const box = strip.current;
    const chip = active ? box?.querySelector<HTMLElement>(`[data-chip="${active}"]`) : null;
    if (!box || !chip || typeof box.scrollTo !== "function") return;
    box.scrollTo({ left: chip.offsetLeft - (box.clientWidth - chip.offsetWidth) / 2, behavior: "smooth" });
  }, [active]);

  if (sections.length < 2) return null;

  function jump(id: string) {
    setActive(id);
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    document.getElementById(id)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }

  return (
    <nav aria-label={label} className="sticky top-14 z-10 -mx-4 border-b border-[#ffa500]/20 bg-black/90 py-2 backdrop-blur-md">
      <div ref={strip} className="no-scrollbar flex snap-x gap-1.5 overflow-x-auto px-4">
        {sections.map((s) => (
          <button
            key={s.id}
            type="button"
            data-chip={s.id}
            onClick={() => jump(s.id)}
            aria-current={active === s.id ? "true" : undefined}
            className="group flex min-h-11 shrink-0 cursor-pointer snap-start items-center rounded-full active:scale-[0.97]"
          >
            <span
              className={cn(
                "flex h-9 items-center rounded-full border px-4 text-[0.8125rem] font-semibold tracking-wide transition-colors",
                active === s.id ? "border-gold bg-gold font-bold text-on-gold" : "border-white/10 bg-card text-muted-foreground group-hover:text-foreground",
              )}
            >
              {s.label}
            </span>
          </button>
        ))}
      </div>
    </nav>
  );
}
