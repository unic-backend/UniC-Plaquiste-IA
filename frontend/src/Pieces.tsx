import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "./api";
import * as I from "./Icons";

/**
 * Calcul par pièce SANS l'IA : le patron saisit ses pièces, le moteur UniC (règles du patron) compte le matériel,
 * la grille de prix chiffre, et le devis se crée comme ceux du chat. Aucun appel payant : marche même API coupée.
 */
type Kind = "ceiling" | "partition" | "paint";
type Room = {
  id: number; kind: Kind; name: string; length: string; width: string; height: string; area: string;
  sides: 1 | 2; doors: string; windows: string; coats: string; hydrofuge: boolean; moulure: boolean; support: "dalle" | "ipn"; suspente: string;
};
const KINDS: [Kind, string][] = [["ceiling", "Faux plafond"], ["partition", "Cloison"], ["paint", "Peinture"]];
const DRAFT = "unic.pieces.v1";   // brouillon sur ce téléphone seulement (confort), jamais une donnée de référence
const money = (n: number | null | undefined) => (n == null ? "—" : Math.round(n).toLocaleString("fr-FR").replace(/ | /g, " "));
const qty = (n: number) => n.toLocaleString("fr-FR", { maximumFractionDigits: 2 }).replace(/ | /g, " ");
// « 16 paquets », « 293 u », « 34,5 m² » : seuls les mots prennent un s
const qtyUnit = (n: number, unit: string) => `${qty(n)} ${n > 1 && /^[a-zà-ÿ]{3,}$/i.test(unit) && !unit.endsWith("s") ? `${unit}s` : unit}`;
const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(/\s/g, "").replace(",", ".")));
const blank = (id: number, kind: Kind = "ceiling"): Room => ({
  id, kind, name: "", length: "", width: "", height: "", area: "", sides: 2, doors: "0", windows: "0", coats: "2",
  hydrofuge: false, moulure: false, support: "dalle", suspente: "",
});

function loadDraft(): { rooms: Room[]; entraxe: string; mo: string } | null {
  try {
    const d = JSON.parse(localStorage.getItem(DRAFT) || "null");
    return d && Array.isArray(d.rooms) && d.rooms.length ? d : null;
  } catch { return null; }
}

function toPayload(r: Room) {
  return {
    name: r.name.trim(), kind: r.kind, length_m: num(r.length), width_m: num(r.width), height_m: num(r.height), area_m2: num(r.area),
    sides: r.sides, doors: num(r.doors) ?? 0, windows: num(r.windows) ?? 0, coats: num(r.coats) ?? 2,
    hydrofuge: r.hydrofuge, moulure: r.moulure, support: r.support, suspente_m: num(r.suspente),
  };
}

function Field({ label, value, onChange, unit, hint }: { label: string; value: string; onChange: (v: string) => void; unit?: string; hint?: string }) {
  return (
    <label>{label}{unit ? ` (${unit})` : ""}
      <input inputMode="decimal" value={value} placeholder={hint} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function RoomCard({ r, i, set, remove, canRemove }: { r: Room; i: number; set: (p: Partial<Room>) => void; remove: () => void; canRemove: boolean }) {
  return (
    <section className="mat-row pc-room" aria-label={`Pièce ${i + 1}`}>
      <div className="mat-head">
        <b>Pièce {i + 1}</b>
        {canRemove && <button className="btn btn-ghost btn-small mat-del" onClick={remove} aria-label={`Retirer la pièce ${i + 1}`}><I.Trash size={16} /> Retirer</button>}
      </div>
      <div className="seg" role="group" aria-label="Type de travaux">
        {KINDS.map(([k, label]) => <button key={k} type="button" className={r.kind === k ? "on" : ""} aria-pressed={r.kind === k} onClick={() => set({ kind: k })}>{label}</button>)}
      </div>
      <div className="mat-fields one">
        <label>Nom de la pièce
          <input value={r.name} maxLength={40} placeholder="Ex. : salon, chambre 1, couloir" onChange={(e) => set({ name: e.target.value })} />
        </label>
      </div>
      {r.kind === "ceiling" && (<>
        <div className="mat-fields">
          <Field label="Longueur" unit="m" value={r.length} onChange={(v) => set({ length: v })} />
          <Field label="Largeur" unit="m" value={r.width} onChange={(v) => set({ width: v })} />
        </div>
        <div className="seg" role="group" aria-label="Accroche">
          <button type="button" className={r.support === "dalle" ? "on" : ""} aria-pressed={r.support === "dalle"} onClick={() => set({ support: "dalle" })}>Dalle (chevilles)</button>
          <button type="button" className={r.support === "ipn" ? "on" : ""} aria-pressed={r.support === "ipn"} onClick={() => set({ support: "ipn" })}>IPN (éclipses)</button>
        </div>
        <div className="mat-fields one">
          <Field label="Hauteur de suspente" unit="m" value={r.suspente} hint="vide = tige de 1 m suffit" onChange={(v) => set({ suspente: v })} />
        </div>
      </>)}
      {r.kind === "partition" && (<>
        <div className="mat-fields">
          <Field label="Longueur" unit="m" value={r.length} onChange={(v) => set({ length: v })} />
          <Field label="Hauteur" unit="m" value={r.height} onChange={(v) => set({ height: v })} />
          <Field label="Portes" value={r.doors} onChange={(v) => set({ doors: v })} />
          <Field label="Fenêtres" value={r.windows} onChange={(v) => set({ windows: v })} />
        </div>
        <div className="seg" role="group" aria-label="Faces">
          <button type="button" className={r.sides === 2 ? "on" : ""} aria-pressed={r.sides === 2} onClick={() => set({ sides: 2 })}>2 faces</button>
          <button type="button" className={r.sides === 1 ? "on" : ""} aria-pressed={r.sides === 1} onClick={() => set({ sides: 1 })}>1 face (doublage)</button>
        </div>
      </>)}
      {r.kind === "paint" && (
        <div className="mat-fields">
          <Field label="Surface" unit="m²" value={r.area} onChange={(v) => set({ area: v })} />
          <Field label="Couches" value={r.coats} onChange={(v) => set({ coats: v })} />
        </div>
      )}
      {r.kind !== "paint" && (
        <div className="pc-opts">
          <label><input type="checkbox" checked={r.hydrofuge} onChange={(e) => set({ hydrofuge: e.target.checked })} /> Pièce humide (plaques hydrofuges)</label>
          {r.kind === "ceiling" && <label><input type="checkbox" checked={r.moulure} onChange={(e) => set({ moulure: e.target.checked })} /> Moulure au tour</label>}
        </div>
      )}
    </section>
  );
}

export function Pieces() {
  const nav = useNavigate();
  const saved = loadDraft();
  const [rooms, setRooms] = useState<Room[]>(saved?.rooms || [blank(1)]);
  const [entraxe, setEntraxe] = useState(saved?.entraxe || "");
  const [mo, setMo] = useState(saved?.mo || "");
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState({ client: "", lieu: "", objet: "" });
  useEffect(() => {
    try { localStorage.setItem(DRAFT, JSON.stringify({ rooms, entraxe, mo })); } catch { /* stockage indisponible : rien à garder */ }
  }, [rooms, entraxe, mo]);
  // Le résultat affiché doit toujours être celui des pièces saisies : toute modification l'efface.
  const edit = (fn: () => void) => { fn(); setRes(null); setErr(""); };
  const setRoom = (id: number, p: Partial<Room>) => edit(() => setRooms((rs) => rs.map((r) => (r.id === id ? { ...r, ...p } : r))));
  const body = () => ({ pieces: rooms.map(toPayload), entraxe_cm: entraxe ? Number(entraxe) : null, main_oeuvre_m2: num(mo) });
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setErr("");
    try { await fn(); } catch (e: any) { setErr(e?.message || "Erreur"); } finally { setBusy(false); }
  };
  const calculer = () => run(async () => { setRes(await api.calcPieces(body())); });
  const devis = () => run(async () => {
    const r = await api.calcPiecesQuote({ ...body(), ...q });
    nav(`/devis/${r.id}`);
  });
  return (
    <div className="page">
      <div className="page-inner mat">
        <h1>Calcul par pièce</h1>
        <p className="lede">Saisis tes pièces : UniC compte le matériel avec tes règles et chiffre avec ta grille de prix.
          Sans l'IA, donc sans crédit API : ça marche toujours.</p>
        <div className="mat-list">
          {rooms.map((r, i) => (
            <RoomCard key={r.id} r={r} i={i} set={(p) => setRoom(r.id, p)} canRemove={rooms.length > 1}
              remove={() => edit(() => setRooms((rs) => rs.filter((x) => x.id !== r.id)))} />
          ))}
        </div>
        <button className="btn btn-line mat-add" disabled={rooms.length >= 40}
          onClick={() => edit(() => setRooms((rs) => [...rs, blank(Math.max(...rs.map((x) => x.id)) + 1, rs[rs.length - 1].kind)]))}>
          <I.Plus size={16} /> Ajouter une pièce
        </button>
        <section className="mat-row pc-set" aria-label="Réglages du calcul">
          <div className="mat-head"><b>Réglages</b></div>
          <div className="seg" role="group" aria-label="Trame des fourrures et montants">
            {[["", "Mon réglage"], ["50", "Trame 50"], ["60", "Trame 60"]].map(([v, label]) => (
              <button key={v} type="button" className={entraxe === v ? "on" : ""} aria-pressed={entraxe === v} onClick={() => edit(() => setEntraxe(v))}>{label}</button>
            ))}
          </div>
          <div className="mat-fields one">
            <Field label="Pose au m²" unit="FCFA" value={mo} hint="vide = fourniture seule" onChange={(v) => edit(() => setMo(v))} />
          </div>
        </section>
        <button className="btn btn-copper pc-go" disabled={busy} onClick={calculer}>{busy && !res ? "Calcul…" : "Calculer le matériel"}</button>
        {err && <p className="error" role="alert">{err}</p>}
        {res && (
          <section className="pc-res" aria-live="polite">
            <p className={res.ok ? "hint ic" : "error"}>{res.ok ? <><I.Check size={16} /> Contrôle indépendant du calcul : OK.</> : "Le contrôle indépendant a trouvé un écart : vérifie les mesures."}</p>
            <div className="pc-table" role="table" aria-label="Matériel et prix">
              <div className="pc-tr pc-th" role="row"><span role="columnheader">Matériel</span><span role="columnheader">Qté</span><span role="columnheader">P.U.</span><span role="columnheader">Montant</span></div>
              {res.lignes.map((l: any) => (
                <div key={`${l.sku}|${l.name}|${l.unit}`} className="pc-tr" role="row">
                  <span role="cell"><b>{l.name}</b></span>
                  <span role="cell">{qtyUnit(l.quantity, l.unit)}</span>
                  <span role="cell">{l.prix_unitaire == null ? <Link to="/materiaux" className="pc-miss">à saisir</Link> : money(l.prix_unitaire)}</span>
                  <span role="cell">{money(l.montant)}</span>
                </div>
              ))}
              {res.main_oeuvre && (
                <div className="pc-tr" role="row">
                  <span role="cell"><b>{res.main_oeuvre.name}</b></span>
                  <span role="cell">{qtyUnit(res.main_oeuvre.quantity, "m²")}</span>
                  <span role="cell">{money(res.main_oeuvre.prix_unitaire)}</span>
                  <span role="cell">{money(res.main_oeuvre.montant)}</span>
                </div>
              )}
              <div className="pc-tr pc-total" role="row"><span role="cell">Total{res.complet ? "" : " (prix manquants exclus)"}</span><span /><span /><span role="cell">{money(res.total)} FCFA</span></div>
            </div>
            {!res.complet && <p className="hint">Prix manquants : {res.prix_manquants.join(", ")}. <Link to="/materiaux">Les saisir dans Matériaux & prix</Link>.</p>}
            <details className="pc-why">
              <summary>Détail du calcul</summary>
              <ul>{res.lignes.map((l: any) => <li key={`${l.sku}|${l.name}|${l.unit}`}><b>{l.name}</b> : {l.formula}</li>)}</ul>
            </details>
            <details className="pc-why">
              <summary>Hypothèses du calcul</summary>
              {res.blocs.map((b: any, i: number) => (
                <div key={i}><b>{b.type} : {b.pieces}</b> ({qty(b.surface_m2)} m²)<ul>{b.hypotheses.map((h: string, j: number) => <li key={j}>{h}</li>)}</ul></div>
              ))}
            </details>
            {res.ok && (
              <form className="mat-row pc-quote" onSubmit={(e) => { e.preventDefault(); devis(); }}>
                <div className="mat-head"><b>Faire le devis</b></div>
                <div className="mat-fields">
                  <label>Client<input value={q.client} maxLength={120} required onChange={(e) => setQ({ ...q, client: e.target.value })} /></label>
                  <label>Lieu<input value={q.lieu} maxLength={120} placeholder="Ex. : Colobane" onChange={(e) => setQ({ ...q, lieu: e.target.value })} /></label>
                </div>
                <div className="mat-fields one">
                  <label>Objet<input value={q.objet} maxLength={900} placeholder="vide = écrit à partir des pièces" onChange={(e) => setQ({ ...q, objet: e.target.value })} /></label>
                </div>
                <div className="row-actions">
                  <button type="submit" className="btn btn-copper" disabled={busy || q.client.trim().length < 2}>{busy ? "Création…" : "Créer le devis"}</button>
                </div>
                <p className="hint">Le devis est créé en brouillon : tu le relis avant de l'envoyer.</p>
              </form>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
