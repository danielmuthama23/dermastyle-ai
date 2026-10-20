"use client";

import { useEffect, useRef, useState } from "react";
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

function getCaptureQuality(canvas: HTMLCanvasElement) {
  const context = canvas.getContext("2d");
  if (!context) {
    return { brightness: 0, shortSide: 0, good: false, reason: "Unable to inspect the captured frame." };
  }

  const width = canvas.width;
  const height = canvas.height;
  const shortSide = Math.min(width, height);
  const centerSize = Math.max(120, Math.floor(shortSide * 0.7));
  const x = Math.max(0, Math.floor((width - centerSize) / 2));
  const y = Math.max(0, Math.floor((height - centerSize) / 2));

  const image = context.getImageData(x, y, centerSize, centerSize);
  let sum = 0;
  for (let i = 0; i < image.data.length; i += 4) {
    const r = image.data[i];
    const g = image.data[i + 1];
    const b = image.data[i + 2];
    sum += (r + g + b) / 3;
  }

  const brightness = sum / (image.data.length / 4);
  const good = shortSide >= 480 && brightness >= 55 && brightness <= 220;

  return {
    brightness,
    shortSide,
    good,
    reason: shortSide < 480
      ? "Move closer so your face fills the frame."
      : brightness < 55
        ? "The frame is too dark. Improve the lighting and retake it."
        : brightness > 220
          ? "The frame is too bright. Turn on softer lighting and retake it."
          : "Face looks well framed for the AI scan.",
  };
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
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    api.createSession().then(s => setSid(s.id)).catch(e => setErr(e.message));
    api.garments().then(g => setGarments(g.garments)).catch(() => {});
    return () => {
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  async function run<T>(label: string, fn: () => Promise<T>): Promise<T | undefined> {
    setErr(null); setBusy(label);
    try { return await fn(); } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  }

  const submitGoal = () => run("Reading your goal…", async () => {
    const { prefs } = await api.setGoal(sid!, goal);
    setPrefs(prefs);
  });

  const stopCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraOpen(false);
  };

  const openCamera = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError("This browser does not support camera capture.");
      return;
    }
    try {
      setCameraError(null);
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "user",
          width: { ideal: 1280 },
          height: { ideal: 1280 },
        },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setCameraOpen(true);
    } catch {
      setCameraError("Unable to access the camera. Please upload a selfie instead.");
    }
  };

  const captureFromCamera = async () => {
    const video = videoRef.current;
    if (!video) {
      setCameraError("Camera preview is not ready yet.");
      return;
    }

    const canvas = document.createElement("canvas");
    const width = video.videoWidth || 1280;
    const height = video.videoHeight || 1280;
    canvas.width = width;
    canvas.height = height;

    const context = canvas.getContext("2d");
    if (!context) {
      setCameraError("Unable to capture the camera frame.");
      return;
    }

    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const metrics = getCaptureQuality(canvas);
    if (!metrics.good) {
      setCameraError(metrics.reason);
      return;
    }

    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(blob => {
        if (!blob) {
          reject(new Error("No image captured from the camera."));
          return;
        }
        resolve(blob);
      }, "image/jpeg", 0.92);
    });

    stopCamera();
    const file = new File([blob], "live-face-scan.jpg", { type: "image/jpeg" });
    await analyze(file, { analysis_mode: "live", capture_source: "camera" });
  };

  const analyze = (file: File, extra: Record<string, string> = {}) => run("Analyzing your skin with YouCam Skin AI. This can take up to a minute…", async () => {
    const { job_id } = await api.startSkin(sid!, file, extra);
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

  const quickScores = skin?.concerns.slice().sort((a, b) => a.ui_score - b.ui_score).slice(0, 4) ?? [];

  return (
    <main className="page-shell">
      <div className="wrap">
        <header className="topbar">
          <div className="brand">Derma<i>Style</i> AI</div>
          <div className="demo-flag">FACE AI · live API demo</div>
        </header>

        <section className="hero" aria-label="Overview">
          <div className="hero-copy">
            <p className="eyebrow">YouCam Skin AI + Clothes Try-On v4</p>
            <h1>
              Happy eyes.<br />
              Better glow.<br />
              <em>One plan</em> you can trust.
            </h1>
            <p className="lede">
              Describe your moment, upload your selfie, and let the app read your skin and outfit intention in real time.
              Every score, recommendation and preview is explained with evidence from the API.
            </p>
            <div className="legend" aria-label="Evidence tags">
              <span><span className="ev measured">measured</span>from YouCam</span>
              <span><span className="ev verified">verified</span>catalog checked</span>
              <span><span className="ev catalog">catalog</span>data reviewed</span>
              <span><span className="ev unknown">unknown</span>needs confirmation</span>
            </div>
          </div>

          <div className="face-stage" aria-live="polite">
            <svg viewBox="0 0 260 320" role="img" aria-label="Face recognition preview">
              <defs>
                <linearGradient id="skinGlow" x1="0" x2="1">
                  <stop offset="0%" stopColor="#c7d2ff" />
                  <stop offset="100%" stopColor="#8de7d3" />
                </linearGradient>
              </defs>
              <rect x="18" y="18" width="224" height="284" rx="28" fill="rgba(18,30,52,0.78)" stroke="rgba(143,170,255,0.3)" />
              <circle cx="130" cy="135" r="76" fill="rgba(255,255,255,0.06)" stroke="url(#skinGlow)" strokeWidth="2" />
              <path d="M95 120c10-26 30-40 35-40s25 14 35 40" fill="none" stroke="#edf1ff" strokeWidth="4" strokeLinecap="round" opacity="0.8" />
              <circle cx="106" cy="124" r="7" fill="#f3dcb6" />
              <circle cx="154" cy="124" r="7" fill="#f3dcb6" />
              <path d="M110 156c12 12 28 18 40 0" fill="none" stroke="#f0d0bf" strokeWidth="4" strokeLinecap="round" />
              <path d="M90 168c18 20 42 32 70 32s52-12 70-32" fill="none" stroke="#7ce3d0" strokeWidth="5" strokeLinecap="round" opacity="0.9" />
              <path d="M118 210l12 18 12-18 12 18 12-18" fill="none" stroke="#d3ddff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" opacity="0.8" />
              <rect x="58" y="42" width="144" height="7" rx="3.5" fill="rgba(143,170,255,0.2)" />
              <rect x="84" y="244" width="92" height="6" rx="3" fill="rgba(141,231,211,0.35)" />
              <rect x="30" y="66" width="6" height="150" rx="3" fill="rgba(255,255,255,0.12)" />
              <rect x="224" y="66" width="6" height="150" rx="3" fill="rgba(255,255,255,0.12)" />
              <path className="scanline" d="M38 118l184 0" stroke="rgba(143,170,255,0.9)" strokeWidth="2" />
            </svg>
            <div className="readout">
              <strong>Face scan:</strong> happy eyes · glow {quickScores[0] ? `${quickScores[0].ui_score}/100` : "ready"}
            </div>
          </div>
        </section>

        <nav className="tabs" aria-label="Steps">
          {STEPS.map(s => (
            <button key={s.id} aria-selected={step === s.id ? "true" : "false"} onClick={() => {
              setStep(s.id); if (s.id === "beauty" && sid) run("Loading…", loadRecs);
            }}>{s.label}</button>
          ))}
        </nav>

        {err && <p className="err" role="alert">{err}</p>}
        {busy && <Busy text={busy} />}
        {sample && <div className="banner">Product data in this build is <strong>sample data</strong>, not real retailer listings.</div>}

        {step === "discover" && (
          <section className="card panel">
            <header>
              <h2>What are you shopping for?</h2>
              <p className="note">Describe the occasion, budget and any must-haves.</p>
            </header>
            <textarea id="goal" value={goal} onChange={e => setGoal(e.target.value)}
              placeholder="Skincare and an elegant outfit for a wedding, under $150, fragrance-free" />
            <div className="row">
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
                <div className="row gap-large">
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
          <section className="card panel">
            <header>
              <h2>Skin Insights</h2>
              <p className="note">Optional. Use a front-facing, well-lit selfie with your face filling most of the frame, hair off your forehead. Skin analysis is cosmetic, not a medical diagnosis.</p>
            </header>
            <Consent checked={faceConsent} onChange={setFaceConsent}>
              I agree to send this photo to YouCam (Perfect Corp) for analysis. It is not stored on our server, and I can delete my results at any time.
            </Consent>
            <div className="row gap-large" style={{ alignItems: "center" }}>
              <button type="button" className="primary" onClick={openCamera} disabled={!faceConsent || !!busy || !sid}>Use live camera</button>
              <button type="button" className="link" onClick={captureFromCamera} disabled={!cameraOpen || !faceConsent || !!busy || !sid}>Capture and analyze</button>
            </div>
            <p className="note">Best result: front-facing light, eyes open, full face centered, hair off the forehead, and no heavy shadows.</p>
            {cameraOpen && (
              <div style={{ position: "relative", width: "100%", maxWidth: 360, marginTop: 12 }}>
                <video ref={videoRef} autoPlay playsInline muted style={{ width: "100%", borderRadius: 16, background: "#111827" }} />
                <div style={{ position: "absolute", inset: 0, border: "2px solid rgba(126, 211, 183, 0.9)", borderRadius: 16, pointerEvents: "none", boxShadow: "inset 0 0 0 9999px rgba(17, 24, 39, 0.16)" }} />
              </div>
            )}
            {cameraError && <p className="err" role="alert">{cameraError}</p>}
            <p className="note">Or upload a selfie file instead:</p>
            <input type="file" accept="image/jpeg,image/png" disabled={!faceConsent || !!busy || !sid}
              aria-label="Upload a face photo" onChange={e => e.target.files?.[0] && analyze(e.target.files[0])} />
            {skin && (
              <div className="score-block">
                {skin.concerns.slice().sort((a, b) => a.ui_score - b.ui_score).map(c => (
                  <div className="score" key={c.key}>
                    <span>{c.label}</span>
                    <div className="bar" role="img" aria-label={`${c.label} ${c.ui_score} out of 100`}><i style={{ width: `${c.ui_score}%` }} /></div>
                    <span>{c.ui_score}</span>
                  </div>
                ))}
                <p className="note"><Evidence kind="measured" /> Higher is better. Scores come directly from YouCam Skin AI and depend on lighting and pose.</p>
                <div className="row gap-large">
                  <button className="primary" onClick={() => { setStep("beauty"); run("Loading…", loadRecs); }}>Next: beauty planner</button>
                  <button className="link" onClick={wipe}>Delete my results</button>
                </div>
              </div>
            )}
            {!skin && <p><button className="link" onClick={() => { setStep("beauty"); run("Loading…", loadRecs); }}>Skip analysis</button></p>}
          </section>
        )}

        {step === "beauty" && (
          <section className="card panel">
            <header>
              <h2>Beauty Planner</h2>
              {!recs && !busy && <p className="note">Nothing to show yet. Describe your goal first.</p>}
            </header>
            {recs && Object.entries(recs).map(([cat, list]) => (
              <div key={cat} className="category-block">
                <h3>{cat}</h3>
                <div className="grid">
                  {list.map(r => (
                    <article key={r.product.id} className={`item ${r.eligible ? "" : "off"}`}>
                      <strong>{r.product.name}</strong>
                      <div className="note">{r.product.brand} · <span className="price">{money(r.product.price)}</span></div>
                      <ul className="reasons">
                        {r.reasons.map((x, i) => <li key={i}><Evidence kind={x.evidence} />{x.text}</li>)}
                        {r.warnings.map((x, i) => <li key={`w${i}`}><Evidence kind={x.evidence} />{x.text}</li>)}
                      </ul>
                      <details>
                        <summary className="note">Ingredients</summary>
                        <p className="note">{r.product.ingredients ? r.product.ingredients.join(", ") : "Not available. Please confirm on the retailer page."}</p>
                        <p className="note">Source: {r.product.provenance.source}</p>
                      </details>
                    </article>
                  ))}
                </div>
              </div>
            ))}
            <div className="row gap-large">
              <button className="primary" onClick={() => setStep("closet")}>Next: virtual closet</button>
              <button className="link" onClick={buildPlan}>Skip to plan</button>
            </div>
          </section>
        )}

        {step === "closet" && (
          <section className="card panel">
            <header>
              <h2>Virtual Closet</h2>
            </header>
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
            <div className="row gap-large">
              <button className="primary" onClick={buildPlan}>Build my plan</button>
              {tryon && <button className="link" onClick={wipe}>Delete my results</button>}
            </div>
          </section>
        )}

        {step === "plan" && (
          <section className="card panel">
            <header>
              <h2>My Shopping Plan</h2>
            </header>
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
      </div>
    </main>
  );
}
