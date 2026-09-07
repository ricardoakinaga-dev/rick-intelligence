"use client";

import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";
import { useEffect, useRef } from "react";

export function Panel({ children, className = "", as: Tag = "section" }: { children: ReactNode; className?: string; as?: "section" | "div" | "article" }) {
  return <Tag className={`panel ${className}`}>{children}</Tag>;
}

export function StatusPill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "success" | "warning" | "danger" | "accent" }) {
  return <span className={`status-pill ${tone}`}><span className="status-dot" aria-hidden="true" />{children}</span>;
}

export function Button({ children, variant = "primary", className = "", ref, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; ref?: Ref<HTMLButtonElement> }) {
  return <button ref={ref} className={`button ${variant} ${className}`} {...props}>{children}</button>;
}

export function Spinner({ label = "Carregando" }: { label?: string }) {
  return <span className="spinner-wrap" role="status"><span className="spinner" aria-hidden="true" /><span className="sr-only">{label}</span></span>;
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-mark" aria-hidden="true">+</div><div><h3>{title}</h3><p>{description}</p>{action ? <div className="empty-action">{action}</div> : null}</div></div>;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirmar",
  busy = false,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const onCancelRef = useRef(onCancel);

  useEffect(() => {
    onCancelRef.current = onCancel;
  }, [onCancel]);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = window.requestAnimationFrame(() => cancelRef.current?.focus());
    return () => {
      window.cancelAnimationFrame(frame);
      const previous = previousFocusRef.current;
      previousFocusRef.current = null;
      if (previous?.isConnected && !previous.hasAttribute("disabled")) previous.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        event.preventDefault();
        onCancelRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>("button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled)"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [busy, open]);

  if (!open) return null;

  return <div className="dialog-backdrop" role="presentation"><section id="confirm-dialog" ref={dialogRef} className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title" aria-describedby="confirm-dialog-description"><span className="eyebrow">Confirmação necessária</span><h2 id="confirm-dialog-title">{title}</h2><p id="confirm-dialog-description">{description}</p><div className="dialog-actions"><Button ref={cancelRef} variant="secondary" onClick={onCancel} disabled={busy}>Cancelar</Button><Button variant="danger" onClick={onConfirm} disabled={busy} aria-busy={busy}>{busy ? <Spinner label="Confirmando exclusão" /> : null}{busy ? "Removendo…" : confirmLabel}</Button></div></section></div>;
}
