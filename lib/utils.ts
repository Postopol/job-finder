import { clsx, type ClassValue } from "clsx";
import { randomUUID } from "node:crypto";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function newId(): string {
  return randomUUID();
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
