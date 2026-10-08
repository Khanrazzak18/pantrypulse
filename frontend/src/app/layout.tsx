import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PantryPulse",
  description: "AI food allocation for Harvest Bridge Food Bank",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-stone-50 text-stone-900 antialiased">{children}</body>
    </html>
  );
}
