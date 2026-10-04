import { useEffect, useState } from "react";
import * as I from "./Icons";
import { net, type InstagramStatus, type Post } from "./api";

/** Connexion Instagram (compte professionnel) : le patron crée son appli Meta, colle l'ID et le secret, puis autorise. */
export function InstagramConnect({ say, onChange }: { say: (m: string) => void; onChange?: () => void }) {
  const [st, setSt] = useState<InstagramStatus | null>(null);
  const [appId, setAppId] = useState("");
  const [secret, setSecret] = useState("");
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const refresh = () => net.instagramStatus().then((s) => { setSt(s); setAppId((a) => a || s.app_id); onChange?.(); }).catch((e) => say(e.message));
  useEffect(() => { refresh(); }, []);
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) say(ok); } catch (e: any) { say(e.message || "Erreur"); } finally { setBusy(false); }
  };
  const copyUri = async () => { try { await navigator.clipboard.writeText(st?.redirect_uri || ""); say("Adresse copiée."); } catch { say("Copie impossible : sélectionne l'adresse."); } };
  if (!st) return null;

  return (
    <section className="card-box">
      <label>Connexion Instagram</label>
      {st.connected ? (
        <>
          <p className="post-body"><I.Check size={16} /> @{st.username || "compte"} relié · {st.days_left ?? "?"} jours</p>
          <p className="hint">Le jeton se prolonge tout seul à chaque publication. Une photo est obligatoire pour publier.</p>
          <div className="row">
            <button className="btn btn-line btn-small" disabled={busy} onClick={() => run(async () => { setLink((await net.instagramAuthUrl()).url); }, "Lien prêt : touche « Ouvrir Instagram ».")}>Reconnecter</button>
            <button className="btn btn-ghost btn-small" disabled={busy}
              onClick={() => { if (window.confirm("Déconnecter Instagram ? Le jeton sera effacé du serveur.")) run(async () => { await net.instagramDisconnect(); await refresh(); }, "Instagram déconnecté."); }}>Déconnecter</button>
          </div>
        </>
      ) : (
        <>
          <p className="hint">Il faut un compte Instagram <b>professionnel</b> (Business ou Créateur) et une appli Meta gratuite. Rien n'est publié sans ton « Publier ».</p>
          <button className="btn btn-line btn-small" onClick={() => setOpen((o) => !o)}>{open ? "Masquer les étapes" : "Voir les étapes"}</button>
          {open && (
            <ol className="steps">
              <li>Instagram → Réglages → <b>Type de compte</b> → passe en <b>compte professionnel</b> (gratuit).</li>
              <li>Ouvre <a href="https://developers.facebook.com/apps/creation/" target="_blank" rel="noopener noreferrer">developers.facebook.com</a> → <b>Créer une appli</b> → cas d'usage <b>Autre</b> → type <b>Entreprise</b>. Nom : UniC AI.</li>
              <li>Dans l'appli : <b>Ajouter un produit</b> → <b>Instagram</b> → <b>API setup with Instagram login</b>.</li>
              <li>Même page : <b>Rôles</b> → <b>Instagram testers</b> → ajoute ton compte, puis accepte l'invitation dans Instagram (Réglages → Applis et sites web).</li>
              <li><b>Business login settings</b> → « Valid OAuth redirect URIs » : ajoute exactement :
                <div className="copy-line"><code>{st.redirect_uri}</code><button className="btn btn-line btn-small" onClick={copyUri}>Copier</button></div></li>
              <li>Copie l'<b>Instagram app ID</b> et l'<b>Instagram app secret</b> (page « API setup »), colle-les ci-dessous.</li>
            </ol>
          )}
          <input inputMode="numeric" autoComplete="off" placeholder="Instagram app ID (chiffres)" value={appId} onChange={(e) => setAppId(e.target.value)} aria-label="Instagram app ID" />
          <input type="password" autoComplete="off" placeholder={st.app_saved ? "Instagram app secret (déjà enregistré)" : "Instagram app secret"} value={secret} onChange={(e) => setSecret(e.target.value)} aria-label="Instagram app secret" />
          <button className="btn btn-copper" disabled={busy || appId.trim().length < 8 || (!secret && !st.app_saved)}
            onClick={() => run(async () => { await net.instagramSaveApp(appId, secret); setSecret(""); setLink((await net.instagramAuthUrl()).url); await refresh(); }, "Enregistré. Touche « Ouvrir Instagram ».")}>
            Enregistrer et connecter
          </button>
        </>
      )}
      {link && <a className="btn btn-copper open-link" href={link} target="_blank" rel="noopener noreferrer">Ouvrir Instagram pour autoriser</a>}
      {link && <button className="btn btn-line btn-small" onClick={() => { setLink(""); refresh(); }}>C'est fait, actualiser</button>}
    </section>
  );
}

/** Publication d'un post Instagram approuvé : la photo est obligatoire. */
export function InstagramPublish({ post, connected, say, onDone }: { post: Post; connected: boolean; say: (m: string) => void; onDone: () => void }) {
  const [photo, setPhoto] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  if (!connected) return <p className="hint">Connecte Instagram ci-dessus pour publier d'ici.</p>;
  const go = async () => {
    if (!photo) return;
    setBusy(true);
    try { await net.instagramPublish(post.id, photo); say("Publié sur Instagram."); onDone(); }
    catch (e: any) { say(e.message || "Publication impossible"); }
    finally { setBusy(false); }
  };
  return (
    <div className="li-publish">
      <label className="btn btn-line btn-small file-btn"><I.Camera size={14} /> {photo ? photo.name.slice(0, 18) : "Choisir la photo (obligatoire)"}
        <input type="file" accept="image/*" hidden onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
      </label>
      <button className="btn btn-copper btn-small" disabled={busy || !photo} onClick={go}>Publier sur Instagram</button>
    </div>
  );
}
