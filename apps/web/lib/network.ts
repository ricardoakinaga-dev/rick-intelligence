"use client";

import { useSyncExternalStore } from "react";

function subscribe(listener: () => void) {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener("online", listener);
  window.addEventListener("offline", listener);
  return () => {
    window.removeEventListener("online", listener);
    window.removeEventListener("offline", listener);
  };
}

function getSnapshot() {
  return typeof navigator === "undefined" ? true : navigator.onLine;
}

function getServerSnapshot() {
  // The server cannot observe the browser connection. An optimistic server
  // snapshot avoids a hydration mismatch; the browser snapshot is reconciled
  // as soon as the subscription is installed.
  return true;
}

export function useOnlineStatus() {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
