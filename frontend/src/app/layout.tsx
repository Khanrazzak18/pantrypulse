import type { Metadata } from "next";
import { ConnectionBanner } from "@/components/connection-banner";
import "./globals.css";

// Every page is rendered per request: that is what lets each response carry its own CSP nonce.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "PantryPulse",
  description: "AI food allocation for Harvest Bridge Food Bank",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-stone-50 text-stone-900 antialiased">
        <ConnectionBanner />
        {children}
      </body>
    </html>
  );
}
