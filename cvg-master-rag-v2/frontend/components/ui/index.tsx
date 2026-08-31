"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TableHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "@/lib/utils";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type BadgeVariant = "neutral" | "success" | "warning" | "danger" | "info";

export function Button({
  className,
  variant = "primary",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button className={cn("ui-button", variant, className)} {...props}>
      {children}
    </button>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn("ui-input", props.className)} {...props} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn("ui-textarea", props.className)} {...props} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn("ui-select", props.className)} {...props} />;
}

export function Card({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("card", className)} {...props}>
      {children}
    </div>
  );
}

export function Badge({
  className,
  variant = "neutral",
  children,
}: HTMLAttributes<HTMLSpanElement> & { variant?: BadgeVariant }) {
  return <span className={cn("badge", variant, className)}>{children}</span>;
}

export function Table({ className, children, ...props }: TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="table-wrap">
      <table className={cn("ui-table", className)} {...props}>
        {children}
      </table>
    </div>
  );
}

export function Tabs({
  items,
  defaultValue,
}: {
  items: Array<{ value: string; label: string; content: ReactNode }>;
  defaultValue?: string;
}) {
  const [active, setActive] = useState(defaultValue ?? items[0]?.value ?? "");

  useEffect(() => {
    if (!active && items[0]) {
      setActive(items[0].value);
    }
  }, [active, items]);

  const current = items.find((item) => item.value === active) ?? items[0];
  if (!current) return null;

  return (
    <div className="tabs">
      <div className="tab-list">
        {items.map((item) => (
          <button
            key={item.value}
            type="button"
            className={cn("tab-button", item.value === active && "active")}
            onClick={() => setActive(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div>{current.content}</div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} />;
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="state-box">
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}

export function ErrorState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="state-box">
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}

function Surface({
  children,
  title,
  onClose,
  className,
}: {
  children: ReactNode;
  title: string;
  onClose: () => void;
  className?: string;
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="overlay" role="presentation" onMouseDown={onClose}>
      <div
        className={cn("modal", className)}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-content">
          <div className="modal-header">
            <div>
              <strong>{title}</strong>
            </div>
            <button className="ui-button ghost" type="button" onClick={onClose} aria-label="Fechar">
              Fechar
            </button>
          </div>
          <div className="modal-body">{children}</div>
        </div>
      </div>
    </div>
  );
}

export function Modal({
  open,
  title,
  children,
  onClose,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  if (!open) return null;
  return <Surface title={title} onClose={onClose}>{children}</Surface>;
}

export function Drawer({
  open,
  title,
  children,
  onClose,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  if (!open) return null;
  return (
    <div className="overlay overlay-drawer" role="presentation" onMouseDown={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawer-content">
          <div className="drawer-header">
            <div>
              <strong>{title}</strong>
            </div>
            <button className="ui-button ghost" type="button" onClick={onClose} aria-label="Fechar">
              Fechar
            </button>
          </div>
          <div className="drawer-body">{children}</div>
        </div>
      </aside>
    </div>
  );
}

type ToastIntent = "success" | "error" | "info";
type ToastItem = {
  id: string;
  title: string;
  description?: string;
  intent?: ToastIntent;
};

const ToastContext = createContext<{
  pushToast: (toast: Omit<ToastItem, "id">) => void;
} | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const pushToast = (toast: Omit<ToastItem, "id">) => {
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setToasts((items) => [...items, { ...toast, id }]);
    window.setTimeout(() => {
      setToasts((items) => items.filter((item) => item.id !== id));
    }, 4200);
  };

  const value = useMemo(() => ({ pushToast }), []);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" aria-live="polite" aria-relevant="additions removals">
        {toasts.map((toast) => (
          <div key={toast.id} className={cn("toast", toast.intent && toast.intent)}>
            <strong>{toast.title}</strong>
            {toast.description ? <p>{toast.description}</p> : null}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used inside ToastProvider");
  }
  return ctx;
}

export function ToastViewport() {
  return null;
}

export function ExternalLink({
  href,
  children,
  className,
}: {
  href: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <a href={href} className={className} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}
