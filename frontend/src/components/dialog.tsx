"use client";

import { type ReactNode, useEffect, useRef } from "react";
import { flushSync } from "react-dom";

/**
 * A modal dialog built on the browser's own <dialog>: while it is open the rest of the page cannot
 * be reached (focus stays inside, Tab and Shift+Tab wrap around), Escape closes it, and focus goes
 * back to whatever opened it. The parent owns `open`; `onClose` is called however it was closed.
 */
export function Dialog({
  open,
  onClose,
  title,
  role = "dialog",
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  role?: "dialog" | "alertdialog"; // "alertdialog" for a confirmation of something that cannot be undone
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const titleId = `${title.replace(/\W+/g, "-").toLowerCase()}-title`;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <dialog
      ref={ref}
      role={role}
      aria-labelledby={titleId}
      onClose={() => {
        // The browser delivers "close" as a later task, after any key press or click that came in
        // meanwhile. If the dialog has been opened again by then, this event is about the old
        // closing and must not close the new one.
        if (ref.current?.open) return;
        flushSync(() => onClose());
        opener.current?.focus();
      }}
      onClick={(e) => {
        if (e.target === ref.current) ref.current?.close(); // a click on the dimmed backdrop
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          // Close and tell the parent now, rather than when the browser gets round to the close event.
          e.preventDefault();
          ref.current?.close();
          flushSync(() => onClose());
          opener.current?.focus();
          return;
        }
        // Keep Tab and Shift+Tab inside: from the last control go to the first, and back.
        if (e.key !== "Tab") return;
        const controls = [...(ref.current?.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])") ?? [])].filter(
          (el) => !(el as HTMLButtonElement).disabled,
        );
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (!first || !last) return;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }}
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-lg p-0 shadow-xl backdrop:bg-black/40"
    >
      <div className="p-5">
        <h2 id={titleId} className="text-lg font-semibold">
          {title}
        </h2>
        {children}
      </div>
    </dialog>
  );
}
