/**
 * Type-Safe POD Studio State Machine & API Client (P2 Frontend Architecture)
 * ==========================================================================
 * Uses Discriminated Unions from `../types/contracts` to eliminate illegal
 * UI state transitions and FormData field hallucinations.
 */

import type {
  PodCompileBlueprintResponse,
  PodPropagateResponse,
  PodSessionPhase,
  PropagationPayload,
} from "../types/contracts";

export interface CompileBlueprintRequest {
  readonly seedFile: File;
  readonly pdfFile?: File | null;
  readonly sessionId?: string | null;
  readonly manualBoundaryAnchor?: string | null;
  readonly manualBoundaryIdx?: number | null;
}

export function buildCompileBlueprintFormData(req: CompileBlueprintRequest): FormData {
  const fd = new FormData();
  fd.append("seed_file", req.seedFile);
  if (req.pdfFile) {
    fd.append("pdf_file", req.pdfFile);
  }
  if (req.sessionId && req.sessionId.trim()) {
    fd.append("session_id", req.sessionId.trim());
  }
  if (req.manualBoundaryAnchor && req.manualBoundaryAnchor.trim()) {
    fd.append("manual_boundary_anchor", req.manualBoundaryAnchor.trim());
  }
  if (typeof req.manualBoundaryIdx === "number" && req.manualBoundaryIdx >= 0) {
    fd.append("manual_boundary_idx", String(req.manualBoundaryIdx));
  }
  return fd;
}

export function buildPropagationFormData(
  payload: PropagationPayload,
  templateFile?: File | null,
): FormData {
  const fd = new FormData();
  fd.append("session_id", payload.session_id);
  fd.append("engine_mode", payload.engine_mode);

  if (templateFile) {
    fd.append("template_file", templateFile);
  }
  if (payload.blueprint_json) {
    fd.append("blueprint_json", payload.blueprint_json);
  }
  if (payload.manual_boundary_anchor) {
    fd.append("manual_boundary_anchor", payload.manual_boundary_anchor);
  }
  if (typeof payload.manual_boundary_idx === "number" && payload.manual_boundary_idx >= 0) {
    fd.append("manual_boundary_idx", String(payload.manual_boundary_idx));
  }

  if (payload.engine_mode === "vlm_continuation") {
    fd.append("model", payload.model);
    if (
      typeof payload.max_continuation_sections === "number" &&
      payload.max_continuation_sections >= 1
    ) {
      fd.append("max_continuation_sections", String(payload.max_continuation_sections));
    }
  }
  return fd;
}

export class PodStudioClient {
  private phase: PodSessionPhase = { phase: "idle" };

  public getPhase(): PodSessionPhase {
    return this.phase;
  }

  public async compileBlueprint(
    req: CompileBlueprintRequest,
  ): Promise<PodCompileBlueprintResponse> {
    this.phase = {
      phase: "compiling_blueprint",
      seedFileName: req.seedFile.name,
      pdfFileName: req.pdfFile?.name,
    };
    const res = await fetch("/api/pod/2_compile_blueprint", {
      method: "POST",
      body: buildCompileBlueprintFormData(req),
    });
    if (!res.ok) {
      const errText = await res.text();
      this.phase = { phase: "error", message: errText };
      throw new Error(errText);
    }
    const data = (await res.json()) as PodCompileBlueprintResponse;
    this.phase = { phase: "blueprint_ready", response: data };
    return data;
  }

  public async propagateAndValidate(
    payload: PropagationPayload,
    templateFile?: File | null,
  ): Promise<PodPropagateResponse> {
    this.phase = {
      phase: "propagating",
      sessionId: payload.session_id,
      payload,
    };
    const res = await fetch("/api/pod/3_propagate_and_validate", {
      method: "POST",
      body: buildPropagationFormData(payload, templateFile),
    });
    if (!res.ok) {
      const errText = await res.text();
      this.phase = { phase: "error", message: errText };
      throw new Error(errText);
    }
    const data = (await res.json()) as PodPropagateResponse;
    this.phase = { phase: "completed", response: data };
    return data;
  }
}

