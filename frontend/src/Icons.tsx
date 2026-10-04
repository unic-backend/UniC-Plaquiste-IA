import type { SVGProps } from "react";

/** Jeu d'icônes unique : trait fin arrondi, 24 px, couleur = texte (currentColor). */
type P = SVGProps<SVGSVGElement> & { size?: number };
const base = (size = 22): SVGProps<SVGSVGElement> => ({
  width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 1.75, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true,
});
const mk = (d: React.ReactNode) => ({ size, ...rest }: P) => <svg {...base(size)} {...rest}>{d}</svg>;

export const Mic = mk(<><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3" /></>);
export const Plus = mk(<path d="M12 5v14M5 12h14" />);
export const ArrowUp = mk(<path d="M12 19V6M6.5 11.5 12 6l5.5 5.5" strokeWidth={2.2} />);
export const Stop = mk(<rect x="7" y="7" width="10" height="10" rx="2.5" fill="currentColor" stroke="none" />);
export const Camera = mk(<><path d="M4 8.5A2.5 2.5 0 0 1 6.5 6h1.2l1-1.5h6.6l1 1.5h1.2A2.5 2.5 0 0 1 20 8.5v8a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 16.5z" /><circle cx="12" cy="12.5" r="3.3" /></>);
export const Image = mk(<><rect x="4" y="5" width="16" height="14" rx="3" /><circle cx="9" cy="10" r="1.6" /><path d="m5 17 4.5-4.5 3.5 3.5 2.5-2.5L20 17" /></>);
export const File = mk(<><path d="M7.5 3.5H13l5 5V19a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 19V5a1.5 1.5 0 0 1 1.5-1.5Z" /><path d="M13 3.5V8.5h5" /></>);
export const Menu = mk(<path d="M4 7h16M4 12h16M4 17h10" />);
export const Settings = mk(<><circle cx="12" cy="12" r="3" /><path d="M19.4 14a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V20a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H4a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H10a1.7 1.7 0 0 0 1-1.5V4a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V10a1.7 1.7 0 0 0 1.5 1H20a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" /></>);
export const Back = mk(<path d="M15 5 8 12l7 7" />);
export const Close = mk(<path d="M6 6l12 12M18 6 6 18" />);
export const Check = mk(<path d="m5 12.5 4.5 4.5L19 7.5" />);
export const Alert = mk(<><path d="M12 4 3 19.5h18z" /><path d="M12 10v4.5M12 17.5v.01" /></>);
export const Sparkle = mk(<path d="M12 3.5 14 10l6.5 2-6.5 2-2 6.5-2-6.5-6.5-2L10 10z" />);
export const Plug = mk(<><path d="M9 3v5M15 3v5M6.5 8h11v3.5a5.5 5.5 0 0 1-11 0zM12 17v4" /></>);
export const Chat = mk(<path d="M5 6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v7a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 3.5V16A2.5 2.5 0 0 1 5 13.5z" />);
export const Megaphone = mk(<><path d="M4 10v4a1 1 0 0 0 1 1h2l7 4V5L7 9H5a1 1 0 0 0-1 1Z" /><path d="M18 9.5a4 4 0 0 1 0 5" /></>);
export const Copy = mk(<><rect x="8.5" y="8.5" width="11" height="11" rx="3" /><path d="M15.5 8.5V7A2.5 2.5 0 0 0 13 4.5H7A2.5 2.5 0 0 0 4.5 7v6A2.5 2.5 0 0 0 7 15.5h1.5" /></>);
export const Dot = mk(<circle cx="12" cy="12" r="4" fill="currentColor" stroke="none" />);
export const Circle = mk(<circle cx="12" cy="12" r="4.5" />);
export const Refresh = mk(<><path d="M19.5 12a7.5 7.5 0 1 1-2.4-5.5" /><path d="M19.5 4.5v4h-4" /></>);
export const Pencil = mk(<><path d="M4.5 19.5 5.3 15 15.8 4.5a2 2 0 0 1 2.9 0l.8.8a2 2 0 0 1 0 2.9L9 18.7z" /><path d="m14 6.5 3.5 3.5" /></>);
export const Eye = mk(<><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" /><circle cx="12" cy="12" r="3" /></>);
export const More = mk(<><circle cx="5.5" cy="12" r="1.4" fill="currentColor" /><circle cx="12" cy="12" r="1.4" fill="currentColor" /><circle cx="18.5" cy="12" r="1.4" fill="currentColor" /></>);
export const Pin = mk(<><path d="M9 4h6l-1 5.5 3 3H7l3-3z" /><path d="M12 12.5V20" /></>);
export const Trash = mk(<><path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12" /><path d="M10 11v5M14 11v5" /></>);
export const Sun = mk(<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>);
export const Moon = mk(<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />);
export const Bell = mk(<path d="M6 9a6 6 0 1 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9zM10 20a2 2 0 0 0 4 0" />);
