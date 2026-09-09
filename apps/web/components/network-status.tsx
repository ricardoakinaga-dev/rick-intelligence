"use client";

import { WifiOff } from "lucide-react";
import { useOnlineStatus } from "@/lib/network";

export function NetworkStatus() {
  const online = useOnlineStatus();
  if (online) return null;

  return (
    <div className="network-banner" data-network-state="offline" role="alert" aria-live="assertive" aria-atomic="true">
      <WifiOff size={17} aria-hidden="true" />
      <div>
        <strong>Sem conexão</strong>
        <span>As ações que dependem do servidor podem não concluir. Tente novamente quando a conexão voltar.</span>
      </div>
    </div>
  );
}
