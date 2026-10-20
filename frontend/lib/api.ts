export type Evidence = "measured" | "verified" | "catalog" | "inferred" | "unknown";
export interface Reason { text: string; evidence: Evidence }
export interface Product {
  id: string; name: string; brand: string; category: string; price: number; currency: string;
  ingredients: string[] | null; targets: string[]; retailer_url?: string | null; provenance: { source: string; verified: boolean };
}
export interface Recommendation {
  product: Product; score: number; eligible: boolean; reasons: Reason[]; warnings: Reason[];
}
export interface SkinConcern { key: string; label: string; ui_score: number; mask_urls: string[] }
export interface SkinReport { concerns: SkinConcern[]; overall: number | null; skin_age: number | null }
export interface Prefs {
  raw_goal: string; occasion: string | null; budget: number | null; fragrance_free: boolean;
  alcohol_free: boolean; style_tags: string[]; want_categories: string[]; want_outfit: boolean;
  simple_routine: boolean;
}
export interface Garment { id: string; name: string; brand: string; price: number; category: string; image_url: string | null }
export interface Bundle {
  label: string; items: Recommendation[]; garment: Garment | null; total: number; score: number;
  within_budget: boolean | null;
}
export interface Plan { prefs: Prefs; bundles: Bundle[]; garment: Garment | null; tryon_url: string | null; notes: string[] }
export interface Job<T = unknown> { id: string; state: "running" | "done" | "failed"; result: T; error: string | null }

export class ApiError extends Error {}

async function parse<T>(r: Response): Promise<T> {
  if (r.ok) return r.json();
  let msg = `Request failed (${r.status})`;
  try {
    const body = await r.json();
    const d = body.detail;
    msg = typeof d === "string" ? d : d?.message ?? msg;
  } catch { /* keep default */ }
  throw new ApiError(msg);
}

export const api = {
  createSession: () => fetch("/api/sessions", { method: "POST" }).then(r => parse<{ id: string }>(r)),
  setGoal: (id: string, text: string) =>
    fetch(`/api/sessions/${id}/goal`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }) })
      .then(r => parse<{ prefs: Prefs }>(r)),
  editPrefs: (id: string, prefs: Prefs) =>
    fetch(`/api/sessions/${id}/prefs`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(prefs) })
      .then(r => parse<{ prefs: Prefs }>(r)),
  startSkin: (id: string, image: File, extras: Record<string, string> = {}) => {
    const f = new FormData(); f.append("image", image); f.append("consent", "true");
    Object.entries(extras).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") {
        f.append(k, v);
      }
    });
    return fetch(`/api/sessions/${id}/skin`, { method: "POST", body: f }).then(r => parse<{ job_id: string }>(r));
  },
  startTryOn: (id: string, person: File, o: { garmentId?: string; garmentUrl?: string; garmentImage?: File | null }) => {
    const f = new FormData(); f.append("person", person); f.append("consent", "true");
    if (o.garmentId) f.append("garment_id", o.garmentId);
    if (o.garmentUrl) f.append("garment_url", o.garmentUrl);
    if (o.garmentImage) f.append("garment_image", o.garmentImage);
    return fetch(`/api/sessions/${id}/tryon`, { method: "POST", body: f }).then(r => parse<{ job_id: string }>(r));
  },
  job: <T,>(jobId: string) => fetch(`/api/jobs/${jobId}`).then(r => parse<Job<T>>(r)),
  recommendations: (id: string) =>
    fetch(`/api/sessions/${id}/recommendations`).then(r => parse<{ ranked: Record<string, Recommendation[]>; has_analysis: boolean; catalog_is_sample: boolean }>(r)),
  products: () => fetch("/api/catalog/products").then(r => parse<{ products: Product[]; sample: boolean }>(r)),
  product: (id: string) => fetch(`/api/catalog/products/${id}`).then(r => parse<Product>(r)),
  garments: () => fetch("/api/catalog/garments").then(r => parse<{ garments: Garment[]; sample: boolean }>(r)),
  plan: (id: string, garmentId?: string) =>
    fetch(`/api/sessions/${id}/plan${garmentId ? `?garment_id=${garmentId}` : ""}`).then(r => parse<Plan>(r)),
  deleteData: (id: string) => fetch(`/api/sessions/${id}/data`, { method: "DELETE" }).then(r => parse<{ deleted: boolean }>(r)),
};

/** Poll a background job until it finishes. */
export async function waitForJob<T>(jobId: string, everyMs = 2000, maxMs = 300_000): Promise<T> {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    const j = await api.job<T>(jobId);
    if (j.state === "done") return j.result;
    if (j.state === "failed") throw new ApiError(j.error ?? "Something went wrong.");
    await new Promise(r => setTimeout(r, everyMs));
  }
  throw new ApiError("That is taking longer than expected. Please try again.");
}
