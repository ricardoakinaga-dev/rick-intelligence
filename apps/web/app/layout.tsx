import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AppShell } from "@/components/app-shell";
import { SessionProvider } from "@/components/session-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "RICK Intelligence",
  description: "Plataforma veterinária de conhecimento com evidências rastreáveis.",
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="pt-BR"><body><SessionProvider><AppShell>{children}</AppShell></SessionProvider></body></html>;
}
