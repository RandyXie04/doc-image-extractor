// @ts-check
/**
 * Runtime-safe POD Studio Contract Helpers (Synchronized with `frontend/src/api/podClient.ts`)
 * Enforces strict FormData field naming and Discriminated Union payload construction.
 */

/**
 * @typedef {Object} CompileBlueprintRequest
 * @property {File} seedFile
 * @property {File | null} [pdfFile]
 * @property {string | null} [sessionId]
 * @property {string | null} [manualBoundaryAnchor]
 * @property {number | null} [manualBoundaryIdx]
 */

/**
 * @param {CompileBlueprintRequest} req
 * @returns {FormData}
 */
export function buildCompileBlueprintFormData(req) {
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
  if (typeof req.manualBoundaryIdx === "number" && !Number.isNaN(req.manualBoundaryIdx) && req.manualBoundaryIdx >= 0) {
    fd.append("manual_boundary_idx", String(req.manualBoundaryIdx));
  }
  return fd;
}

if (typeof window !== "undefined") {
  // Expose on window for inline script consumption in pod_studio.html
  // @ts-ignore
  window["PodContracts"] = {
    buildCompileBlueprintFormData,
  };
}

