"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import { Badge, Card } from "@/components/ui";

function ForbiddenContent() {
  const [from, setFrom] = useState("/");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const nextFrom = new URLSearchParams(window.location.search).get("from") || "/";
    setFrom(nextFrom);
  }, []);

  return (
    <div className="auth-page">
      <div className="auth-shell auth-shell-single">
        <Card className="auth-hero">
          <div className="page-hero">
            <span className="eyebrow">Acesso negado</span>
            <h1>Seu perfil não pode abrir este módulo.</h1>
            <p>
              A rota solicitada exige permissões acima do seu papel atual. Volte para o console ou entre com um perfil
              com escopo apropriado.
            </p>
          </div>
          <div className="auth-metrics">
            <Badge variant="warning">
              <ShieldAlert size={14} />
              acesso negado
            </Badge>
            <Badge variant="neutral">origem {from}</Badge>
          </div>
          <div className="auth-links">
            <Link href="/">Voltar ao início</Link>
            <Link href="/login">Trocar sessão</Link>
          </div>
        </Card>
      </div>
    </div>
  );
}

export default function ForbiddenPage() {
  return <ForbiddenContent />;
}
