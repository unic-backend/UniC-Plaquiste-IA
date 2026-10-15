import { useState } from "react";
import { VideoStudio } from "./Site";

/** Page « Studio vidéo » (menu latéral). */
export function VideoPage() {
  const [msg, setMsg] = useState("");
  return (
    <div className="page">
      <div className="page-inner">
        {msg && <p className="hint" role="status">{msg}</p>}
        <VideoStudio say={setMsg} />
      </div>
    </div>
  );
}
