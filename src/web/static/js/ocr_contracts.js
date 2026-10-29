// @ts-check
/**
 * Browser-Native Runtime Contract Validators for Automated Draft Workbench (`ocr_pipeline.html`)
 * Synchronized with `frontend/src/types/contracts.ts` & `src/web/schemas.py`.
 */

/**
 * @param {unknown} raw
 * @returns {{ task_id?: string | null, progress: number, message: string, status: string, error?: string | null }}
 */
export function assertOcrProgressContract(raw) {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new Error("[ContractViolation] OcrProgressResponse must be an object.");
  }
  const obj = /** @type {Record<string, unknown>} */ (raw);
  if (typeof obj.progress !== "number" || typeof obj.message !== "string" || typeof obj.status !== "string") {
    throw new Error("[ContractViolation] OcrProgressResponse missing required fields (progress, message, status).");
  }
  return /** @type {{ task_id?: string | null, progress: number, message: string, status: string, error?: string | null }} */ (obj);
}

/**
 * @param {unknown} raw
 * @returns {{ fonts: Array<Record<string, unknown>>, docx_styles: string[], default_roles: string[] }}
 */
export function assertFontScanContract(raw) {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new Error("[ContractViolation] FontScanResponse must be an object.");
  }
  const obj = /** @type {Record<string, unknown>} */ (raw);
  if (!Array.isArray(obj.fonts) || !Array.isArray(obj.docx_styles)) {
    throw new Error("[ContractViolation] FontScanResponse missing fonts[] or docx_styles[].");
  }
  return /** @type {{ fonts: Array<Record<string, unknown>>, docx_styles: string[], default_roles: string[] }} */ (obj);
}

if (typeof window !== "undefined") {
  // @ts-ignore
  window.OcrContracts = {
    assertOcrProgressContract,
    assertFontScanContract,
  };
}
