import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import * as I from "./Icons";

/** Higgsfield : création d'images depuis la conversation. Les clés sont chiffrées sur le serveur et ne s'affichent plus jamais. */
export function Higgsfield() {
  const [st, setSt] = useState<{ connected: boolean; per_day: number; left_today: number } | null>(null);
  const [f, setF] = useState({ key_id: "", secret: "" });
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => { api.higgsfield().then(setSt).catch((e) => setMsg(e?.message || "Erreur")); }, []);
  useEffect(() => { load(); }, [load]);
  const connect = async () => {
    setBusy(true); setMsg("");
    try { setSt(await api.higgsfieldConnect(f)); setF({ key_id: "", secret: "" }); setMsg("Higgsfield est connecté."); }
    catch (e: any) { setMsg(e?.message || "Erreur"); } finally { setBusy(false); }
  };
  const disconnect = async () => {
    if (!window.confirm("Déconnecter Higgsfield ? Les clés enregistrées seront effacées.")) return;
    try { await api.higgsfieldDisconnect(); setMsg(""); load(); } catch (e: any) { setMsg(e?.message || "Erreur"); }
  };
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Higgsfield</h1>
        <p className="lede">Demande une image dans la conversation : « fais-moi un rendu du salon avec un plafond lambris chêne clair ». UniC la crée et te la montre.</p>
        {msg && <p className="hint" role="status">{msg}</p>}
        {st && (
          <section className="card-box">
            {st.connected ? (
              <>
                <p className="hint ic"><I.Check size={16} /> Connecté · {st.left_today} image(s) restante(s) aujourd'hui sur {st.per_day}</p>
                <button className="btn btn-ghost btn-small" onClick={disconnect}>Déconnecter</button>
              </>
            ) : (
              <>
                <ol className="at-steps">
                  <li>Sur <b>console.higgsfield.ai</b>, crée une clé d'API (identifiant + secret).</li>
                  <li>Colle les deux ici. Ils sont chiffrés sur le serveur et ne s'affichent plus jamais.</li>
                </ol>
                <div className="at-form">
                  <input autoComplete="off" placeholder="Identifiant de la clé" value={f.key_id} onChange={(e) => setF({ ...f, key_id: e.target.value })} />
                  <input type="password" autoComplete="off" placeholder="Secret" value={f.secret} onChange={(e) => setF({ ...f, secret: e.target.value })} />
                  <button className="btn btn-copper btn-small" disabled={busy || f.key_id.trim().length < 6 || f.secret.trim().length < 6} onClick={connect}>
                    {busy ? "Vérification…" : "Connecter"}</button>
                </div>
              </>
            )}
          </section>
        )}
        <section className="card-box">
          <h3>À savoir</h3>
          <ul className="hint">
            <li>Chaque image consomme tes crédits Higgsfield. UniC n'en crée qu'une par demande, et seulement quand tu la demandes.</li>
            <li>Limite de sécurité : {st?.per_day ?? 10} images par jour.</li>
            <li>L'image est une illustration, jamais un plan d'exécution ni un métré. Rien n'est publié ni envoyé sans ton clic.</li>
          </ul>
        </section>
      </div>
    </div>
  );
}
