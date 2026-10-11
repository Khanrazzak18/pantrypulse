import type { Metadata } from "next";
import { ConnectionBanner } from "@/components/connection-banner";
import { SiteFooter } from "@/components/site-footer";
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
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:inline-flex focus:min-h-11 focus:items-center focus:left-2 focus:top-2 focus:z-[60] focus:rounded-md focus:bg-white focus:px-4 focus:py-2 focus:font-medium focus:text-green-900 focus:shadow-lg"
        >
          Skip to main content
        </a>
        <ConnectionBanner />
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
