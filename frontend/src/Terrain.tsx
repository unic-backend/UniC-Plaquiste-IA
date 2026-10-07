import { useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Terrain : pointage chantier (arrivée / départ, GPS si accordé) et signature client sur un devis. */

const QKEY = "unic.checkins";
type Queued = { client_id: string; kind: "in" | "out"; project_id?: string; at: string; lat?: number; lon?: number; accuracy_m?: number };

const uid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
const hours = (h: number) => `${Math.floor(h)} h ${String(Math.round((h % 1) * 60)).padStart(2, "0")}`;
const when = (iso: string) => new Date(iso).toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function readQ(): Queued[] { try { const v = JSON.parse(localStorage.getItem(QKEY) || "[]"); return Array.isArray(v) ? v : []; } catch { return []; } }
function writeQ(l: Queued[]) { try { localStorage.setItem(QKEY, JSON.stringify(l)); } catch { /* stockage indisponible */ } }

function position(): Promise<{ lat: number; lon: number; accuracy_m: number } | null> {
  return new Promise((res) => {
    if (!navigator.geolocation) return res(null);
    navigator.geolocation.getCurrentPosition(
      (p) => res({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy_m: p.coords.accuracy }),
      () => res(null),   // refusé ou indisponible : le pointage part sans position, rien n'est inventé
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 },
    );
  });
}

export function Pointage() {
  const [projects, setProjects] = useState<any[]>([]);
  const [pid, setPid] = useState("");
  const [rows, setRows] = useState<any[]>([]);
  const [sum, setSum] = useState<any>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [queued, setQueued] = useState(readQ().length);

  const load = () => {
    api.checkins().then(setRows).catch(() => {});
    api.checkinSummary().then(setSum).catch(() => {});
  };
  const flush = async () => {   // renvoie les pointages faits sans réseau (le serveur ignore un pointage déjà reçu)
    for (;;) {
      const list = readQ();
      if (!list.length) break;
      try { await api.checkin(list[0]); }
      catch (e: any) { if (!navigator.onLine || /réseau|connexion|fetch/i.test(e?.message || "")) break; }   // refus définitif du serveur : on abandonne ce pointage
      writeQ(readQ().slice(1));
    }
    setQueued(readQ().length);
    load();
  };
  useEffect(() => {
    api.projects().then(setProjects).catch(() => {});
    void flush();
    window.addEventListener("online", flush);
    return () => window.removeEventListener("online", flush);
  }, []);

  async function punch(kind: "in" | "out") {
    setBusy(true); setMsg("");
    const pos = await position();
    const item: Queued = { client_id: uid(), kind, project_id: pid || undefined, at: new Date().toISOString(), ...(pos || {}) };
    try {
      await api.checkin(item);
      setMsg(`${kind === "in" ? "Arrivée" : "Départ"} enregistré${pos ? " avec la position" : " (sans position : GPS non accordé)"}.`);
      load();
    } catch (e: any) {
      if (navigator.onLine) setMsg(e?.message || "Erreur");
      else { writeQ([...readQ(), item]); setQueued(readQ().length); setMsg("Pas de réseau : pointage gardé avec son heure réelle, envoyé au retour."); }
    } finally { setBusy(false); }
  }

  return (
    <div className="page"><div className="page-inner">
      <h1>Pointage</h1>
      <p className="lede">Arrivée et départ du chantier, avec l'heure et la position du téléphone.</p>
      {msg && <p className="hint" role="status">{msg}</p>}
      {queued > 0 && <p className="hint">{queued} pointage(s) en attente de réseau.</p>}
      <section className="card-box">
        <label>Chantier
          <select value={pid} onChange={(e) => setPid(e.target.value)}>
            <option value="">Sans chantier précis</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <div className="row-actions">
          <button className="btn btn-copper" disabled={busy} onClick={() => punch("in")}>Arrivée</button>
          <button className="btn btn-line" disabled={busy} onClick={() => punch("out")}>Départ</button>
        </div>
      </section>
      {sum && (sum.chantiers.length > 0 || sum.en_cours.length > 0) && (
        <section className="card-box"><h3>Heures</h3>
          {sum.chantiers.map((c: any) => <p key={c.project_id || "x"}><b>{c.project}</b> : {hours(c.heures)}</p>)}
          {sum.en_cours.map((c: any) => <p key={"o" + (c.project_id || "x")} className="hint">{c.project} : en cours depuis {when(c.depuis)} (non compté)</p>)}
        </section>
      )}
      <section className="card-box"><h3>Derniers pointages</h3>
        {!rows.length && <p className="hint">Aucun pointage.</p>}
        {rows.slice(0, 15).map((r) => (
          <p key={r.id}>{r.kind === "in" ? "Arrivée" : "Départ"} · {r.project || "Sans chantier"} · {when(r.at)}{r.lat == null ? " · sans position" : ""}</p>
        ))}
      </section>
    </div></div>
  );
}

/** Signature du client sur le téléphone : dessin au doigt, nom, case « Bon pour accord ». */
export function SignaturePanel({ quoteId }: { quoteId: string }) {
  const cv = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const [name, setName] = useState("");
  const [ok, setOk] = useState(false);
  const [inked, setInked] = useState(false);
  const [msg, setMsg] = useState("");
  const [list, setList] = useState<any[]>([]);
  const load = () => api.quoteSignatures(quoteId).then(setList).catch(() => {});
  useEffect(() => { load(); }, [quoteId]);

  const at = (e: React.PointerEvent) => { const r = cv.current!.getBoundingClientRect(); return [(e.clientX - r.left) * (cv.current!.width / r.width), (e.clientY - r.top) * (cv.current!.height / r.height)]; };
  const down = (e: React.PointerEvent) => { drawing.current = true; cv.current!.setPointerCapture(e.pointerId); const c = cv.current!.getContext("2d")!; const [x, y] = at(e); c.beginPath(); c.moveTo(x, y); };
  const move = (e: React.PointerEvent) => {
    if (!drawing.current) return;
    const c = cv.current!.getContext("2d")!; const [x, y] = at(e);
    c.lineWidth = 3; c.lineCap = "round"; c.strokeStyle = "#111"; c.lineTo(x, y); c.stroke(); setInked(true);
  };
  const clear = () => { const c = cv.current!; c.getContext("2d")!.clearRect(0, 0, c.width, c.height); setInked(false); };
  async function save() {
    setMsg("");
    try {
      await api.signQuote(quoteId, { name, image: cv.current!.toDataURL("image/png"), consent: ok });
      clear(); setName(""); setOk(false); setMsg("Signature enregistrée."); load();
    } catch (e: any) { setMsg(e?.message || "Erreur"); }
  }

  return (
    <section className="card-box">
      <h3>Signature du client</h3>
      {list.map((a) => (
        <p key={a.id}>Signé par <b>{a.signer_name}</b> le {when(a.signed_at)}{" "}
          {a.unchanged_since_signature ? <span className="hint">· devis inchangé depuis</span> : <span className="error">· devis modifié après la signature</span>}</p>
      ))}
      <input placeholder="Nom du client" value={name} onChange={(e) => setName(e.target.value)} />
      <canvas ref={cv} width={600} height={220} aria-label="Zone de signature"
        style={{ width: "100%", maxWidth: 480, height: "auto", border: "1px dashed currentColor", borderRadius: 8, touchAction: "none", background: "#fff" }}
        onPointerDown={down} onPointerMove={move} onPointerUp={() => { drawing.current = false; }} onPointerLeave={() => { drawing.current = false; }} />
      <label><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} /> Bon pour accord</label>
      <div className="row-actions">
        <button className="btn btn-line btn-small" onClick={clear}>Effacer</button>
        <button className="btn btn-copper btn-small" disabled={!inked || !ok || name.trim().length < 2} onClick={save}>Enregistrer la signature</button>
      </div>
      {msg && <p className="hint" role="status">{msg}</p>}
      <p className="hint">Enregistre un accord daté avec l'empreinte du devis. Ce n'est pas une signature électronique qualifiée.</p>
    </section>
  );
}
