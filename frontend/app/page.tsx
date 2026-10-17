"use client";

import { useEffect, useState } from "react";
import {
  api, waitForJob, type Garment, type Plan, type Prefs, type Recommendation, type SkinReport,
} from "../lib/api";

type Step = "discover" | "skin" | "beauty" | "closet" | "plan";
const STEPS: { id: Step; label: string }[] = [
  { id: "discover", label: "1 Discover" }, { id: "skin", label: "2 Skin Insights" },
  { id: "beauty", label: "3 Beauty Planner" }, { id: "closet", label: "4 Virtual Closet" },
  { id: "plan", label: "5 My Plan" },
];

const money = (n: number) => `$${n.toFixed(2)}`;

function Evidence({ kind }: { kind: string }) {
  return <span className={`ev ${kind}`} title={EV_HELP[kind]}>{kind}</span>;
}
const EV_HELP: Record<string, string> = {
  measured: "Returned by YouCam Skin AI for your photo",
  verified: "From catalog data a person has verified",
  catalog: "From catalog data that has not been verified yet",
  inferred: "A rule-based suggestion, not a fact",
  unknown: "Information is missing. Please confirm before buying",
};

function Busy({ text }: { text: string }) {
  return <p role="status" aria-live="polite"><span className="spinner" aria-hidden />{text}</p>;
}

function Consent({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) {
  return (
    <label className="consent">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      <span>{children}</span>
    </label>
  );
}

export default function Home() {
  const [sid, setSid] = useState<string | null>(null);
  const [step, setStep] = useState<Step>("discover");
  const [goal, setGoal] = useState("");
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [skin, setSkin] = useState<SkinReport | null>(null);
  const [recs, setRecs] = useState<Record<string, Recommendation[]> | null>(null);
  const [sample, setSample] = useState(false);
  const [garments, setGarments] = useState<Garment[]>([]);
  const [garmentId, setGarmentId] = useState<string | undefined>();
  const [garmentUrl, setGarmentUrl] = useState("");
  const [garmentFile, setGarmentFile] = useState<File | null>(null);
  const [tryon, setTryon] = useState<string | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [faceConsent, setFaceConsent] = useState(false);
  const [bodyConsent, setBodyConsent] = useState(false);

  useEffect(() => {
    api.createSession().then(s => setSid(s.id)).catch(e => setErr(e.message));
    api.garments().then(g => setGarments(g.garments)).catch(() => {});
  }, []);

  async function run<T>(label: string, fn: () => Promise<T>): Promise<T | undefined> {
    setErr(null); setBusy(label);
    try { return await fn(); } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  }

  const submitGoal = () => run("Reading your goal…", async () => {
    const { prefs } = await api.setGoal(sid!, goal);
    setPrefs(prefs);
  });

  const analyze = (file: File) => run("Analyzing your skin with YouCam Skin AI. This can take up to a minute…", async () => {
    const { job_id } = await api.startSkin(sid!, file);
    const report = await waitForJob<SkinReport>(job_id);
    setSkin(report);
    await loadRecs();
  });

  const loadRecs = async () => {
    const r = await api.recommendations(sid!);
    setRecs(r.ranked); setSample(r.catalog_is_sample);
  };

  const doTryOn = (person: File) => run("Generating your try-on preview…", async () => {
    const { job_id } = await api.startTryOn(sid!, person, { garmentId, garmentUrl: garmentUrl || undefined, garmentImage: garmentFile });
    const res = await waitForJob<{ image_url: string }>(job_id);
    setTryon(res.image_url);
  });

  const buildPlan = () => run("Building your plan…", async () => {
    setPlan(await api.plan(sid!, garmentId)); setStep("plan");
  });

  const wipe = () => run("Deleting your data…", async () => {
    await api.deleteData(sid!); setSkin(null); setTryon(null); setPlan(null); setRecs(null);
    setFaceConsent(false); setBodyConsent(false);
  });

  return (
    <main>
      <h1>DermaStyle AI</h1>
      <p className="tag">Your skin. Your style. One shopping plan you can trust.</p>
      <nav aria-label="Steps">
        {STEPS.map(s => (
          <button key={s.id} aria-current={step === s.id ? "step" : undefined} onClick={() => {
            setStep(s.id); if (s.id === "beauty" && sid) run("Loading…", loadRecs);
          }}>{s.label}</button>
        ))}
      </nav>

      {err && <p className="err" role="alert">{err}</p>}
      {busy && <Busy text={busy} />}
      {sample && <div className="banner">Product data in this build is <strong>sample data</strong>, not real retailer listings.</div>}

      {step === "discover" && (
        <section className="card">
          <h2>What are you shopping for?</h2>
          <label htmlFor="goal" className="note">Describe the occasion, budget and any must-haves.</label>
          <textarea id="goal" value={goal} onChange={e => setGoal(e.target.value)}
            placeholder="Skincare and an elegant outfit for a wedding, under $150, fragrance-free" />
          <div className="row" style={{ marginTop: 8 }}>
            <button className="primary" disabled={!sid || !goal.trim() || !!busy} onClick={submitGoal}>Understand my goal</button>
          </div>
          {prefs && (
            <>
              <div className="chips" aria-label="What we understood">
                {prefs.occasion && <span className="chip">occasion: {prefs.occasion}</span>}
                {prefs.budget != null && <span className="chip">budget: {money(prefs.budget)}</span>}
                {prefs.fragrance_free && <span className="chip">fragrance-free</span>}
                {prefs.alcohol_free && <span className="chip">alcohol-free</span>}
                {prefs.simple_routine && <span className="chip">simple routine</span>}
                {prefs.style_tags.map(t => <span key={t} className="chip">{t}</span>)}
                {prefs.want_categories.map(c => <span key={c} className="chip">{c}</span>)}
              </div>
              <div className="row">
                <label className="consent"><input type="checkbox" checked={prefs.fragrance_free}
                  onChange={async e => setPrefs((await api.editPrefs(sid!, { ...prefs, fragrance_free: e.target.checked })).prefs)} /> Fragrance-free only</label>
                <button className="primary" onClick={() => setStep("skin")}>Next: skin insights</button>
              </div>
              <p className="note">Not right? Edit the text above and run it again. Nothing here is a medical judgement.</p>
            </>
          )}
        </section>
      )}

      {step === "skin" && (
        <section className="card">
          <h2>Skin Insights</h2>
          <p className="note">Optional. Use a front-facing, well-lit selfie with your face filling most of the frame, hair off your forehead. Skin analysis is cosmetic, not a medical diagnosis.</p>
          <Consent checked={faceConsent} onChange={setFaceConsent}>
            I agree to send this photo to YouCam (Perfect Corp) for analysis. It is not stored on our server, and I can delete my results at any time.
          </Consent>
          <input type="file" accept="image/jpeg,image/png" disabled={!faceConsent || !!busy || !sid}
            aria-label="Upload a face photo" onChange={e => e.target.files?.[0] && analyze(e.target.files[0])} />
          {skin && (
            <div style={{ marginTop: 16 }}>
              {skin.concerns.slice().sort((a, b) => a.ui_score - b.ui_score).map(c => (
                <div className="score" key={c.key}>
                  <span>{c.label}</span>
                  <div className="bar" role="img" aria-label={`${c.label} ${c.ui_score} out of 100`}><i style={{ width: `${c.ui_score}%` }} /></div>
                  <span>{c.ui_score}</span>
                </div>
              ))}
              <p className="note"><Evidence kind="measured" /> Higher is better. Scores come directly from YouCam Skin AI and depend on lighting and pose.</p>
              <div className="row"><button className="primary" onClick={() => { setStep("beauty"); run("Loading…", loadRecs); }}>Next: beauty planner</button>
                <button className="link" onClick={wipe}>Delete my results</button></div>
            </div>
          )}
          {!skin && <p><button className="link" onClick={() => { setStep("beauty"); run("Loading…", loadRecs); }}>Skip analysis</button></p>}
        </section>
      )}

      {step === "beauty" && (
        <section className="card">
          <h2>Beauty Planner</h2>
          {!recs && !busy && <p className="note">Nothing to show yet. Describe your goal first.</p>}
          {recs && Object.entries(recs).map(([cat, list]) => (
            <div key={cat} style={{ marginBottom: 16 }}>
              <h3 style={{ textTransform: "capitalize", margin: "8px 0" }}>{cat}</h3>
              <div className="grid">
                {list.map(r => (
                  <article key={r.product.id} className={`item ${r.eligible ? "" : "off"}`}>
                    <strong>{r.product.name}</strong>
                    <div className="note">{r.product.brand} · <span className="price">{money(r.product.price)}</span></div>
                    <ul className="reasons">
                      {r.reasons.map((x, i) => <li key={i}><Evidence kind={x.evidence} />{x.text}</li>)}
                      {r.warnings.map((x, i) => <li key={`w${i}`}><Evidence kind={x.evidence} />{x.text}</li>)}
                    </ul>
                    <details><summary className="note">Ingredients</summary>
                      <p className="note">{r.product.ingredients ? r.product.ingredients.join(", ") : "Not available. Please confirm on the retailer page."}</p>
                      <p className="note">Source: {r.product.provenance.source}</p>
                    </details>
                  </article>
                ))}
              </div>
            </div>
          ))}
          <div className="row"><button className="primary" onClick={() => setStep("closet")}>Next: virtual closet</button>
            <button className="link" onClick={buildPlan}>Skip to plan</button></div>
        </section>
      )}

      {step === "closet" && (
        <section className="card">
          <h2>Virtual Closet</h2>
          <div className="grid">
            {garments.map(g => (
              <button key={g.id} className="item" aria-pressed={garmentId === g.id} onClick={() => setGarmentId(g.id)}
                style={{ textAlign: "left", cursor: "pointer", borderColor: garmentId === g.id ? "var(--accent)" : undefined, background: "var(--card)", color: "var(--ink)", font: "inherit" }}>
                <strong>{g.name}</strong><div className="note">{g.brand} · {money(g.price)} · {g.category.replace("_", " ")}</div>
                {!g.image_url && <div className="note">No product image yet. Add one below.</div>}
              </button>
            ))}
          </div>
          <h3>Garment image</h3>
          <p className="note">Use a front-facing product photo of a single garment, or an https image URL.</p>
          <input type="url" placeholder="https://…/garment.png" value={garmentUrl} onChange={e => setGarmentUrl(e.target.value)} aria-label="Garment image URL" />
          <p><input type="file" accept="image/jpeg,image/png" aria-label="Upload a garment image" onChange={e => setGarmentFile(e.target.files?.[0] ?? null)} /></p>
          <Consent checked={bodyConsent} onChange={setBodyConsent}>
            I agree to send my photo to YouCam (Perfect Corp) to generate a try-on preview. Use a standing, front-facing, full-length photo with only you in it.
          </Consent>
          <input type="file" accept="image/jpeg,image/png" aria-label="Upload a full-body photo"
            disabled={!bodyConsent || !!busy || !sid || !garmentId && !garmentUrl && !garmentFile}
            onChange={e => e.target.files?.[0] && doTryOn(e.target.files[0])} />
          {tryon && (
            <figure><img className="result" src={tryon} alt="Virtual try-on preview" />
              <figcaption className="note">Visual preview only. It does not guarantee fit, comfort, fabric behavior or final appearance.</figcaption></figure>
          )}
          <div className="row"><button className="primary" onClick={buildPlan}>Build my plan</button>
            {tryon && <button className="link" onClick={wipe}>Delete my results</button>}</div>
        </section>
      )}

      {step === "plan" && (
        <section className="card">
          <h2>My Shopping Plan</h2>
          {!plan && <p className="note">Build a plan from the previous steps.</p>}
          {plan?.tryon_url && <img className="result" src={plan.tryon_url} alt="Try-on preview" style={{ maxWidth: 280 }} />}
          {plan?.bundles.map((b, i) => (
            <article key={i} className="item" style={{ margin: "12px 0" }}>
              <strong>{b.label}</strong>
              <ul className="reasons">
                {b.items.map(r => <li key={r.product.id}>{r.product.name} <span className="note">({r.product.category})</span> <span className="price">{money(r.product.price)}</span></li>)}
                {b.garment && <li>{b.garment.name} <span className="note">(outfit)</span> <span className="price">{money(b.garment.price)}</span></li>}
              </ul>
              <p className="price">Total {money(b.total)}{b.within_budget === false && <span className="err"> · over budget</span>}</p>
            </article>
          ))}
          {plan && plan.bundles.length === 0 && <p>No products met your constraints. Try relaxing one.</p>}
          {plan?.notes.map((n, i) => <p key={i} className="note">{n}</p>)}
        </section>
      )}
    </main>
  );
}
