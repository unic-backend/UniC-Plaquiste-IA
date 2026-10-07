import { useEffect, useState } from "react";
import * as I from "./Icons";
import { api, net, type Post } from "./api";
import { sharePhoto } from "./Google";

type Say = (m: string) => void;
const KINDS: { id: string; label: string; hint: string }[] = [
  { id: "devis", label: "Envoyer un devis", hint: "Ex. devis faux plafond salon, 250 000 FCFA (le prix doit venir de toi)" },
  { id: "relance", label: "Relancer un devis", hint: "Ex. devis envoyé il y a 5 jours, pas de réponse" },
  { id: "merci", label: "Merci fin de chantier", hint: "Ex. chantier cloisons terminé aujourd'hui" },
  { id: "avis", label: "Demander un avis Google", hint: "Ex. client très satisfait de son plafond" },
  { id: "rdv", label: "Rendez-vous visite", hint: "Ex. visite jeudi 10 h à Mermoz" },
  { id: "statut", label: "Statut WhatsApp", hint: "Ex. cloison terminée à Diamniadio" },
];

/** Messages WhatsApp rédigés par l'IA : le patron les envoie lui-même depuis son WhatsApp. */
export function WhatsAppStudio({ say, onDraft }: { say: Say; onDraft: () => void }) {
  const [kind, setKind] = useState("devis");
  const [customers, setCustomers] = useState<{ id: string; name: string; phone: string }[]>([]);
  const [cid, setCid] = useState("");
  const [phone, setPhone] = useState("");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.customers().then(setCustomers).catch(() => {}); }, []);
  const k = KINDS.find((x) => x.id === kind)!;
  const go = async () => {
    setBusy(true);
    try { await net.whatsappMessage(kind, cid, phone, details); setDetails(""); onDraft(); say("Message prêt : voir « Brouillons » plus bas."); }
    catch (e: any) { say(e.message || "Erreur"); } finally { setBusy(false); }
  };
  return (
    <section className="card-box">
      <label>Message WhatsApp</label>
      <p className="hint">Ton WhatsApp normal suffit. L'IA rédige ; « Ouvrir WhatsApp » ouvre la discussion avec le message prêt, tu appuies sur envoyer.</p>
      <div className="kw">{KINDS.map((x) => <button key={x.id} className={kind === x.id ? "on" : ""} aria-pressed={kind === x.id} onClick={() => setKind(x.id)}>{x.label}</button>)}</div>
      {kind !== "statut" && (
        <>
          <select value={cid} onChange={(e) => setCid(e.target.value)} aria-label="Client">
            <option value="">Client : choisir (ou saisir un numéro)</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}{c.phone ? ` · ${c.phone}` : ""}</option>)}
          </select>
          <input inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Numéro WhatsApp (ex. 77 123 45 67)" aria-label="Numéro WhatsApp" />
        </>
      )}
      <textarea rows={3} value={details} onChange={(e) => setDetails(e.target.value)} placeholder={k.hint} aria-label="Détails vrais à utiliser" />
      <button className="btn btn-copper" disabled={busy} onClick={go}>Rédiger avec l'IA</button>
    </section>
  );
}

/** Ouvrir la discussion (numéro du client) avec le texte prêt, ou partager un statut avec photo. */
export function WhatsAppActions({ post, say }: { post: Post & { external_id?: string }; say: Say }) {
  const [photo, setPhoto] = useState<File | null>(null);
  const phone = (post.external_id || "").replace(/\D/g, "");
  const statut = post.title === "Statut WhatsApp";
  const open = () => window.open(`https://wa.me/${phone}?text=${encodeURIComponent(post.body)}`, "_blank");
  const share = async () => { try { say(await sharePhoto(photo, post.body, "WhatsApp › Statut", "Statut WhatsApp")); } catch { say("Partage annulé."); } };
  return (
    <div className="li-publish">
      {!statut && <button className="btn btn-copper btn-small" onClick={open}>{phone ? "Ouvrir WhatsApp avec ce client" : "Ouvrir WhatsApp (choisir le contact)"}</button>}
      {statut && (
        <>
          <label className="btn btn-line btn-small file-btn"><I.Camera size={14} /> {photo ? photo.name.slice(0, 18) : "Ajouter une photo"}
            <input type="file" accept="image/*,video/*" hidden onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
          </label>
          <button className="btn btn-copper btn-small" onClick={share}>Partager (Statut)</button>
        </>
      )}
    </div>
  );
}
