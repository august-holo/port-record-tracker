import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import "./globals.css";

const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains", display: "swap" });

export const metadata: Metadata = {
  title: "Terminal State Archive",
  description:
    "What the Seattle–Tacoma terminals published about their state, captured, hashed and timestamped, as a dated record for demurrage and detention disputes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={jetbrains.variable}>
      <body>{children}</body>
    </html>
  );
}
