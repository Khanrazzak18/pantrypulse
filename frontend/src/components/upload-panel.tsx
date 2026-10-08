"use client";

import { useRouter } from "next/navigation";
import { type DragEvent, useRef, useState } from "react";

import { ApiRequestError, apiUpload, type DonationDetail } from "@/lib/api/client";
import { ALLOWED_EXTENSIONS, ALLOWED_TYPES_TEXT, checkUploadFile } from "@/lib/donations";

type State =
  | { kind: "idle" }
  | { kind: "uploading"; file: File }
  | { kind: "error"; message: string; file: File | null };

export function UploadPanel() {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const uploading = state.kind === "uploading";

  async function send(file: File) {
    const problem = checkUploadFile(file.name, file.size);
    if (problem) {
      setState({ kind: "error", message: problem, file: null });
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ kind: "uploading", file });
    const form = new FormData();
    form.append("file", file);
    try {
      const donation = await apiUpload<DonationDetail>("/api/donations", form, controller.signal);
      router.push(`/coordinator/donations/${donation.id}`);
      // Stay in the uploading state while the review page loads.
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setState({ kind: "idle" });
        return;
      }
      const message =
        err instanceof ApiRequestError ? err.message : "Something went wrong. Please try again.";
      // Keep the file for "Try again" when the failure was the network or the server, not the file.
      const canRetry = err instanceof ApiRequestError ? err.status === 0 || err.status >= 500 : true;
      setState({ kind: "error", message, file: canRetry ? file : null });
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file && !uploading) void send(file);
  }

  return (
    <section aria-labelledby="upload-heading" className="rounded-lg border border-stone-200 bg-white p-4">
      <h2 id="upload-heading" className="text-lg font-semibold">
        Add a donation
      </h2>
      <p className="mt-1 text-sm text-stone-600">
        Upload an email, PDF or photo of a manifest. The AI reads it, and you check the result
        before anything is added to inventory.
      </p>

      {state.kind === "error" && (
        <div role="alert" className="mt-3 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          <p className="font-medium">{state.message}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {state.file && (
              <button
                type="button"
                onClick={() => void send(state.file as File)}
                className="rounded-md bg-red-700 px-3 py-1.5 font-medium text-white hover:bg-red-800"
              >
                Try again
              </button>
            )}
            <button
              type="button"
              onClick={() => setState({ kind: "idle" })}
              className="rounded-md border border-red-300 bg-white px-3 py-1.5 font-medium text-red-900 hover:bg-red-100"
            >
              Choose a different file
            </button>
          </div>
        </div>
      )}

      {uploading ? (
        <div role="status" aria-live="polite" className="mt-3 flex items-center gap-3 rounded-md border border-stone-200 bg-stone-50 p-4">
          <svg className="h-5 w-5 shrink-0 animate-spin text-green-700" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" />
            <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
          </svg>
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">Reading {state.file.name}…</p>
            <p className="text-sm text-stone-600">This usually takes 5 to 30 seconds.</p>
          </div>
          <button
            type="button"
            onClick={() => abortRef.current?.abort()}
            className="rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-stone-100"
          >
            Cancel
          </button>
        </div>
      ) : (
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`mt-3 flex cursor-pointer flex-col items-center justify-center rounded-md border-2 border-dashed p-6 text-center focus-within:ring-2 focus-within:ring-green-300 ${
            dragging ? "border-green-700 bg-green-50" : "border-stone-300 hover:bg-stone-50"
          }`}
        >
          <span className="font-medium text-green-800">Choose a file</span>
          <span className="text-sm text-stone-600">or drop it here</span>
          <span className="mt-1 text-xs text-stone-500">
            {ALLOWED_TYPES_TEXT}, up to 10 MB
          </span>
          <input
            ref={inputRef}
            type="file"
            accept={ALLOWED_EXTENSIONS.join(",")}
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void send(file);
            }}
          />
        </label>
      )}
    </section>
  );
}
