/**
 * Strict TypeScript API Client for Automated Draft & Font Mapping Workbench (`ocr_pipeline.html`)
 * ===============================================================================================
 * Enforces P2/P3 Iron Rule 2 & 3: Schema-Driven Development + Discriminated Union State Machine.
 */

import type {
  FontMappingSaveRequest,
  FontMappingSaveResponse,
  FontScanResponse,
  HardwareStatusResponse,
  MarkdownRebuildRequest,
  MarkdownRebuildResponse,
  OcrFileUploadResponse,
  OcrProgressResponse,
  OcrRunStartResponse,
  QueueTasksResponse,
  UpdateCheckResponse,
} from "../types/contracts";

function assertRecord(val: unknown, label: string): Record<string, unknown> {
  if (typeof val !== "object" || val === null || Array.isArray(val)) {
    throw new Error(`[ContractViolation] ${label} must be a non-null object.`);
  }
  return val as Record<string, unknown>;
}

export function validateOcrProgressResponse(raw: unknown): OcrProgressResponse {
  const obj = assertRecord(raw, "OcrProgressResponse");
  if (typeof obj.progress !== "number" || typeof obj.message !== "string" || typeof obj.status !== "string") {
    throw new Error("[ContractViolation] OcrProgressResponse missing required fields (progress, message, status).");
  }
  return obj as unknown as OcrProgressResponse;
}

export function validateFontScanResponse(raw: unknown): FontScanResponse {
  const obj = assertRecord(raw, "FontScanResponse");
  if (!Array.isArray(obj.fonts) || !Array.isArray(obj.docx_styles)) {
    throw new Error("[ContractViolation] FontScanResponse missing fonts[] or docx_styles[].");
  }
  return obj as unknown as FontScanResponse;
}

export async function uploadOcrFile(file: File): Promise<OcrFileUploadResponse> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/upload_file", { method: "POST", body: fd });
  const data: unknown = await res.json();
  if (!res.ok) {
    const errObj = assertRecord(data, "ErrorResponse");
    throw new Error(String(errObj.detail ?? `HTTP ${res.status}`));
  }
  const obj = assertRecord(data, "OcrFileUploadResponse");
  if (typeof obj.file_id !== "string" || typeof obj.filename_stem !== "string") {
    throw new Error("[ContractViolation] Invalid OcrFileUploadResponse payload.");
  }
  return obj as unknown as OcrFileUploadResponse;
}

export async function scanPdfFonts(params: {
  fileId: string;
  filenameOrig?: string;
}): Promise<FontScanResponse> {
  const res = await fetch("/api/scan_fonts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_id: params.fileId, filename_orig: params.filenameOrig ?? "" }),
  });
  const data: unknown = await res.json();
  if (!res.ok) {
    const errObj = assertRecord(data, "ErrorResponse");
    throw new Error(String(errObj.detail ?? `HTTP ${res.status}`));
  }
  return validateFontScanResponse(data);
}

export async function saveFontMapping(payload: FontMappingSaveRequest): Promise<FontMappingSaveResponse> {
  const res = await fetch("/api/save_font_mapping", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data: unknown = await res.json();
  if (!res.ok) {
    const errObj = assertRecord(data, "ErrorResponse");
    throw new Error(String(errObj.detail ?? `HTTP ${res.status}`));
  }
  return assertRecord(data, "FontMappingSaveResponse") as unknown as FontMappingSaveResponse;
}

export async function fetchOcrProgress(stem: string): Promise<OcrProgressResponse> {
  const res = await fetch(`/api/ocr_progress/${encodeURIComponent(stem)}`);
  const data: unknown = await res.json();
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return validateOcrProgressResponse(data);
}

export async function fetchQueueTasks(limit = 50): Promise<QueueTasksResponse> {
  const res = await fetch(`/api/queue/tasks?limit=${limit}`);
  const data: unknown = await res.json();
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return assertRecord(data, "QueueTasksResponse") as unknown as QueueTasksResponse;
}

export async function rebuildDocxFromMarkdown(
  stem: string,
  payload: MarkdownRebuildRequest
): Promise<MarkdownRebuildResponse> {
  const res = await fetch(`/api/update_and_rebuild_docx/${encodeURIComponent(stem)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data: unknown = await res.json();
  if (!res.ok) {
    const errObj = assertRecord(data, "ErrorResponse");
    throw new Error(String(errObj.detail ?? `HTTP ${res.status}`));
  }
  return assertRecord(data, "MarkdownRebuildResponse") as unknown as MarkdownRebuildResponse;
}

export async function fetchHardwareStatus(): Promise<HardwareStatusResponse> {
  const res = await fetch("/api/hardware_status");
  const data: unknown = await res.json();
  return assertRecord(data, "HardwareStatusResponse") as unknown as HardwareStatusResponse;
}

export async function fetchUpdateStatus(): Promise<UpdateCheckResponse> {
  const res = await fetch("/api/check_update");
  const data: unknown = await res.json();
  return assertRecord(data, "UpdateCheckResponse") as unknown as UpdateCheckResponse;
}

export type { OcrRunStartResponse };
