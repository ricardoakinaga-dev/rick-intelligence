"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Activity, BookOpen, ChevronRight, CircleUserRound, LogOut, Menu, MessageSquareText, Search, ShieldCheck, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { useSession } from "@/components/session-provider";
import { Button, Spinner, StatusPill } from "@/components/ui";
import { isAdministrativeRole, presentRole } from "@/lib/presentation";

const nav = [
  { href: "/app", label: "Visão geral", caption: "Seu espaço de trabalho", icon: Activity },
  { href: "/app/documents", label: "Documentos", caption: "Acervo e importações", icon: BookOpen },
  { href: "/app/search", label: "Busca", caption: "Encontrar evidência", icon: Search },
  { href: "/app/chat", label: "Perguntas", caption: "Respostas e fontes", icon: MessageSquareText },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { session, ready, signOut } = useSession();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [mobileViewport, setMobileViewport] = useState(() => typeof window !== "undefined" && window.matchMedia("(max-width: 900px)").matches);
  const railRef = useRef<HTMLElement>(null);
  const railCloseRef = useRef<HTMLButtonElement>(null);
  const mobileMenuRef = useRef<HTMLButtonElement>(null);
  const wasMobileOpen = useRef(false);
  const logoutPending = useRef(false);
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [logoutFailed, setLogoutFailed] = useState(false);

  async function handleLogout() {
    if (logoutPending.current) return;
    logoutPending.current = true;
    setLogoutBusy(true);
    try {
      await signOut();
      setLogoutFailed(false);
    } catch {
      // This notice belongs to logout, survives the login redirect, and never
      // exposes server error details or conflates a login error with logout.
      setLogoutFailed(true);
    } finally {
      logoutPending.current = false;
      setLogoutBusy(false);
    }
  }

  const logoutNotice = logoutFailed ? <div className="form-alert" role="alert" aria-label="Falha ao sair"><ShieldCheck size={16} /><span>O conteúdo privado foi ocultado, mas não foi possível confirmar a saída no servidor.</span><Button variant="secondary" onClick={() => void handleLogout()} disabled={logoutBusy} aria-busy={logoutBusy}>{logoutBusy ? "Tentando sair…" : "Tentar sair novamente"}</Button></div> : null;

  useEffect(() => {
    // A new authenticated session supersedes the old logout operation. Do not
    // offer a retry that would now target this different session.
    if (session) setLogoutFailed(false);
  }, [session]);

  useEffect(() => {
    if (ready && !session && pathname !== "/login") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [pathname, ready, router, session]);

  useLayoutEffect(() => setMobileOpen(false), [pathname]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px)");
    const update = () => setMobileViewport(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!mobileViewport) setMobileOpen(false);
  }, [mobileViewport]);

  useLayoutEffect(() => {
    const focusTarget = mobileOpen ? railCloseRef : wasMobileOpen.current ? mobileMenuRef : null;
    wasMobileOpen.current = mobileOpen;
    if (!focusTarget) return;
    if (mobileOpen) railRef.current?.removeAttribute("inert");
    const focusIsOwnedByTransition = () => {
      const active = document.activeElement;
      if (mobileOpen) return active === document.body || active === mobileMenuRef.current || active === railCloseRef.current;
      return active === document.body || active === railCloseRef.current || Boolean(active && railRef.current?.contains(active));
    };
    const focus = () => {
      if (mobileOpen && railRef.current && getComputedStyle(railRef.current).visibility !== "visible") return;
      if (!focusIsOwnedByTransition()) return;
      focusTarget.current?.focus({ preventScroll: true });
    };
    focus();
    const frame = window.requestAnimationFrame(focus);
    const transitionFallback = mobileOpen ? window.setTimeout(focus, 260) : null;
    return () => {
      window.cancelAnimationFrame(frame);
      if (transitionFallback !== null) window.clearTimeout(transitionFallback);
    };
  }, [mobileOpen]);

  useLayoutEffect(() => {
    if (!mobileViewport || !mobileOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [mobileOpen, mobileViewport]);

  if (pathname === "/login") return <>{logoutNotice}{children}</>;
  if (!ready || !session) return <>{logoutNotice}<div className="app-loading"><Spinner label="Validando sua sessão" /><p>Validando sua identidade e as permissões do espaço de trabalho.</p></div></>;

  const adminNav = { href: "/admin", label: "Administração", caption: "Controles operacionais", icon: ShieldCheck };
  const allNav = [...nav, adminNav];
  const visibleNav = isAdministrativeRole(session.role) || isAdministrativeRole(session.canonical_role)
    ? allNav
    : nav;
  const current = allNav.find((item) => pathname === item.href) ?? allNav[0];
  const mobileRailHidden = mobileViewport && !mobileOpen;
  const handleRailKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (!mobileViewport || !mobileOpen) return;
    if (event.key === "Escape") {
      event.preventDefault();
      setMobileOpen(false);
      return;
    }
    if (event.key !== "Tab") return;
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled)"));
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  const openMobileNavigation = () => setMobileOpen(true);

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">Pular para o conteúdo</a>
      <aside id="product-navigation" ref={railRef} onKeyDown={handleRailKeyDown} className={`rail ${mobileOpen ? "open" : ""}`} aria-label="Navegação do produto" aria-hidden={mobileRailHidden || undefined} inert={mobileRailHidden ? true : undefined}>
        <div className="rail-topline"><span className="brand-mark">R</span><span className="brand-lockup"><strong>RICK</strong><small>intelligence</small></span><button ref={railCloseRef} className="icon-button rail-close" onClick={() => setMobileOpen(false)} aria-label="Fechar navegação"><X size={18} /></button></div>
        <div className="rail-context"><span className="context-kicker">Espaço de trabalho</span><strong>{session.workspace_id}</strong><span className="context-status"><span className="status-dot" aria-hidden="true" />Sessão protegida</span></div>
        <nav className="rail-nav">
          <span className="rail-label">Operação</span>
          {visibleNav.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href;
            return <Link key={item.href} href={item.href} className={`rail-link ${active ? "active" : ""}`} title={item.caption} aria-current={active ? "page" : undefined}><Icon size={18} strokeWidth={active ? 2.4 : 1.8} /><span><strong>{item.label}</strong><small>{item.caption}</small></span>{active ? <ChevronRight size={15} className="rail-chevron" /> : null}</Link>;
          })}
        </nav>
        <div className="rail-bottom"><div className="rail-trust"><ShieldCheck size={16} /><span><strong>Fontes em primeiro lugar</strong><small>Confira a origem antes da confiança</small></span></div><button className="profile-button" onClick={() => void handleLogout()} disabled={logoutBusy}><span className="avatar"><CircleUserRound size={19} /></span><span><strong>{session.email}</strong><small>{presentRole(session.canonical_role || session.role)}</small></span><LogOut size={15} /></button></div>
      </aside>
      {mobileOpen ? <button className="scrim" aria-label="Fechar menu lateral" onClick={() => setMobileOpen(false)} /> : null}
      <div className="workspace">
        <header className="topbar"><div className="topbar-leading"><button ref={mobileMenuRef} className="icon-button mobile-menu" onClick={openMobileNavigation} aria-label="Abrir navegação" aria-expanded={mobileOpen} aria-controls="product-navigation"><Menu size={19} /></button><div className="breadcrumb"><span>RICK Intelligence</span><ChevronRight size={14} /><strong>{current.label}</strong></div></div><div className="topbar-trailing"><span className="session-context" role="group" aria-label={`Espaço de trabalho ${session.workspace_id}; função ${presentRole(session.canonical_role || session.role)}`}><strong>{session.workspace_id}</strong><small>{presentRole(session.canonical_role || session.role)}</small></span><StatusPill tone="accent"><span className="session-status-full">Sessão protegida</span><span className="session-status-short" aria-hidden="true">Protegida</span></StatusPill><span className="topbar-divider" /><span className="role-label">{presentRole(session.canonical_role || session.role)}</span></div></header>
        <main key={JSON.stringify([session.session_id, session.user_id, session.tenant_id, session.workspace_id, session.role, session.canonical_role])} id="main-content" className="main-content">{logoutNotice}{children}</main>
      </div>
    </div>
  );
}
