/**
 * Strict TypeScript API Client for Formula, Image Extraction & Founder Repair Workbenches
 * =======================================================================================
 * Covers P2-C (`formula.html`) and P2-D (`extract_images.html`, `founder_repair.html`).
 */

import type {
  ExtractImagesResponse,
  FormulaTaskStatusResponse,
  FormulaTaskSubmitResponse,
  FounderRepairResponse,
} from "../types/contracts";

function assertRecord(val: unknown, label: string): Record<string, unknown> {
  if (typeof val !== "object" || val === null || Array.isArray(val)) {
    throw new Error(`[ContractViolation] ${label} must be a non-null object.`);
  }
  return val as Record<string, unknown>;
}

export async function submitFormulaTask(formData: FormData): Promise<FormulaTaskSubmitResponse> {
  const res = await fetch("/api/process", { method: "POST", body: formData });
  const data: unknown = await res.json();
  if (!res.ok) {
    const errObj = assertRecord(data, "ErrorResponse");
    throw new Error(String(errObj.detail ?? `HTTP ${res.status}`));
  }
  const obj = assertRecord(data, "FormulaTaskSubmitResponse");
  if (typeof obj.task_id !== "string") {
    throw new Error("[ContractViolation] FormulaTaskSubmitResponse missing task_id.");
  }
  return obj as unknown as FormulaTaskSubmitResponse;
}

export async function fetchFormulaTaskStatus(taskId: string): Promise<FormulaTaskStatusResponse> {
  const res = await fetch(`/api/status/${encodeURIComponent(taskId)}`);
  const data: unknown = await res.json();
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const obj = assertRecord(data, "FormulaTaskStatusResponse");
  if (typeof obj.status !== "string" || typeof obj.progress !== "number") {
    throw new Error("[ContractViolation] FormulaTaskStatusResponse missing status or progress.");
  }
  return obj as unknown as FormulaTaskStatusResponse;
}

export async function submitExtractImages(formData: FormData): Promise<ExtractImagesResponse> {
  const res = await fetch("/api/extract_images", { method: "POST", body: formData });
  const data: unknown = await res.json();
  if (!res.ok) {
    const errObj = assertRecord(data, "ErrorResponse");
    throw new Error(String(errObj.detail ?? `HTTP ${res.status}`));
  }
  return assertRecord(data, "ExtractImagesResponse") as unknown as ExtractImagesResponse;
}

export async function submitFounderRepair(formData: FormData): Promise<FounderRepairResponse> {
  const res = await fetch("/api/founder/repair", { method: "POST", body: formData });
  const data: unknown = await res.json();
  if (!res.ok) {
    const errObj = assertRecord(data, "ErrorResponse");
    throw new Error(String(errObj.detail ?? `HTTP ${res.status}`));
  }
  return assertRecord(data, "FounderRepairResponse") as unknown as FounderRepairResponse;
}

