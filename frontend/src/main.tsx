import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";
import { applyTheme } from "./theme";
import { syncDesktopWorker } from "./api";
import { Capacitor } from "@capacitor/core";
import { wakeApi } from "./phone";

applyTheme();
syncDesktopWorker();

/** Ouvert par « Hey UniC » : on arrive directement sur UniC vocal, qui démarre tout seul. */
async function detectWake(): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  try {
    if (await wakeApi.isWakeLaunch()) {
      (window as unknown as { __unicWake?: boolean }).__unicWake = true;
      window.history.replaceState(null, "", "/unic");
    }
  } catch { /* version sans mot d'appel : ouverture normale */ }
}

detectWake().finally(() => {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </React.StrictMode>
  );
});
