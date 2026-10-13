import { Component, type ReactNode } from "react";

type Props = { children: ReactNode; resetKey?: string; full?: boolean };
type State = { error: Error | null; key?: string };

/** Un écran qui plante n'emporte plus toute l'appli (écran vide sans explication) : message clair, nouvel essai, et changer d'écran remet à zéro. */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey !== state.key ? { key: props.resetKey, error: null } : null;   // autre écran : on repart d'un état sain
  }

  componentDidCatch(error: Error, info: { componentStack?: string | null }) {
    console.error("Écran en erreur :", error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className={this.props.full ? "login" : "page"}>
        <div className={this.props.full ? "login-card" : "page-inner"} role="alert">
          <h2>Cet écran a rencontré un problème</h2>
          <p className="hint">Rien n'est perdu : tes devis, factures et conversations sont enregistrés sur le serveur. Réessaie, ou reviens à l'accueil.</p>
          <p className="error">{this.state.error.message.slice(0, 160)}</p>
          <div className="toolbar">
            <button className="btn btn-copper" onClick={() => this.setState({ error: null })}>Réessayer</button>
            <button className="btn btn-line" onClick={() => { window.location.href = "/"; }}>Accueil</button>
          </div>
        </div>
      </div>
    );
  }
}
