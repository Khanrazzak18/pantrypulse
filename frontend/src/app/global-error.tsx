"use client";

// Replaces the whole page when even the root layout fails. It must bring its own <html> and <body>.
export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0, padding: "3rem 1rem", background: "#fafaf9" }}>
        <div role="alert" style={{ maxWidth: 560, margin: "0 auto", border: "1px solid #fca5a5", background: "#fef2f2", borderRadius: 8, padding: 20 }}>
          <h1 style={{ margin: 0, fontSize: 20, color: "#7f1d1d" }}>Something went wrong</h1>
          <p style={{ color: "#991b1b" }}>PantryPulse hit a problem it could not recover from. Please try again.</p>
          <button type="button" onClick={reset} style={{ minHeight: 44, padding: "0 16px", border: 0, borderRadius: 6, background: "#b91c1c", color: "#fff", fontWeight: 600, cursor: "pointer" }}>
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
