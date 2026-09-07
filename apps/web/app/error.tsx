"use client";

import { Button } from "@/components/ui";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <div className="page-narrow"><div className="error-state"><span className="eyebrow">Falha recuperável</span><h1>A plataforma encontrou um desvio.</h1><p>O erro foi contido. Tente novamente; se persistir, preserve o identificador da solicitação exibido pela API.</p><Button onClick={reset}>Tentar novamente</Button></div></div>;
}
