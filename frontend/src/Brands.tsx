/** Logos des connecteurs dans leurs vraies couleurs (SVG en ligne : aucune image à charger, nets à toute taille). */
type P = { size?: number };
const S = ({ size = 20, children }: { size?: number; children: React.ReactNode }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden focusable="false">{children}</svg>
);

export const Gmail = ({ size }: P) => (
  <S size={size}>
    <rect x="2" y="4.5" width="20" height="15" rx="2.2" fill="#fff" />
    <path d="M2 6.7v11.1c0 .9.7 1.7 1.6 1.7H6V9.6L2 6.7Z" fill="#4285F4" />
    <path d="M22 6.7v11.1c0 .9-.7 1.7-1.6 1.7H18V9.6l4-2.9Z" fill="#34A853" />
    <path d="M18 4.5h2.4c.9 0 1.6.7 1.6 1.6v.6l-4 2.9V4.5Z" fill="#FBBC04" />
    <path d="M6 9.6V4.5H3.6C2.7 4.5 2 5.2 2 6.1v.6l4 2.9Z" fill="#C5221F" />
    <path d="M6 4.5 12 9l6-4.5V9.6L12 14 6 9.6V4.5Z" fill="#EA4335" />
  </S>
);

export const Calendar = ({ size }: P) => (
  <S size={size}>
    <rect x="3" y="3" width="18" height="18" rx="3" fill="#fff" stroke="#DADCE0" strokeWidth=".8" />
    <path d="M3 6a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v3H3V6Z" fill="#4285F4" />
    <rect x="3" y="18" width="6" height="3" rx="1.5" fill="#34A853" />
    <rect x="15" y="18" width="6" height="3" rx="1.5" fill="#FBBC04" />
    <rect x="18" y="9" width="3" height="9" fill="#EA4335" />
    <rect x="3" y="9" width="3" height="9" fill="#188038" />
    <text x="12" y="17" textAnchor="middle" fontSize="8.5" fontWeight="700" fill="#4285F4" fontFamily="Arial, sans-serif">31</text>
  </S>
);

export const GoogleG = ({ size }: P) => (
  <S size={size}>
    <path d="M21.6 12.2c0-.7-.1-1.3-.2-1.9H12v3.7h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 3-4.300 3-7.300Z" fill="#4285F4" />
    <path d="M12 22c2.700 0 5-.9 6.600-2.400l-3.200-2.500c-.9.600-2 1-3.400 1-2.600 0-4.800-1.800-5.600-4.100H3.100v2.600A10 10 0 0 0 12 22Z" fill="#34A853" />
    <path d="M6.400 13.900a6 6 0 0 1 0-3.800V7.500H3.100a10 10 0 0 0 0 9l3.300-2.600Z" fill="#FBBC04" />
    <path d="M12 6c1.500 0 2.800.5 3.900 1.500l2.900-2.900A10 10 0 0 0 3.100 7.500l3.300 2.600C7.200 7.800 9.400 6 12 6Z" fill="#EA4335" />
  </S>
);

export const GitHub = ({ size }: P) => (
  <S size={size}>
    <path style={{ fill: "var(--ink, #111)" }} d="M12 .3a12 12 0 0 0-3.800 23.400c.6.1.8-.3.8-.6v-2c-3.300.7-4-1.600-4-1.600-.6-1.400-1.400-1.800-1.400-1.800-1-.7.1-.7.1-.7 1.200.1 1.800 1.200 1.800 1.200 1.100 1.800 2.800 1.300 3.500 1 .1-.8.4-1.300.8-1.600-2.700-.3-5.500-1.300-5.500-5.900 0-1.300.5-2.400 1.200-3.200-.1-.4-.5-1.600.1-3.200 0 0 1-.3 3.300 1.200a11.500 11.500 0 0 1 6 0C17.300 4.700 18.300 5 18.300 5c.7 1.700.2 2.900.1 3.200.8.800 1.200 1.900 1.200 3.200 0 4.600-2.800 5.600-5.500 5.900.4.400.8 1.100.8 2.200v3.300c0 .3.2.7.8.6A12 12 0 0 0 12 .3Z" />
  </S>
);

export const Canva = ({ size }: P) => (
  <S size={size}>
    <defs>
      <linearGradient id="canva-g" x1="4" y1="4" x2="20" y2="20" gradientUnits="userSpaceOnUse">
        <stop offset="0" stopColor="#00C4CC" /><stop offset="1" stopColor="#7D2AE8" />
      </linearGradient>
    </defs>
    <circle cx="12" cy="12" r="10.5" fill="url(#canva-g)" />
    <path d="M15.800 14.500c-.6 1.600-1.900 2.600-3.500 2.600-2.100 0-3.600-1.800-3.600-4.100 0-2.400 1.600-4.300 3.700-4.300 1.200 0 2.200.6 2.700 1.600" fill="none" stroke="#fff" strokeWidth="1.700" strokeLinecap="round" />
  </S>
);

/** Higgsfield : repère simplifié (monogramme), pas le logo officiel. */
export const Higgsfield = ({ size }: P) => (
  <S size={size}>
    <rect x="2" y="2" width="20" height="20" rx="5.500" fill="#111" />
    <path d="M8 7v10M16 7v10M8 12h8" stroke="#fff" strokeWidth="2.200" strokeLinecap="round" fill="none" />
  </S>
);

export const Pdf = ({ size }: P) => (
  <S size={size}>
    <path d="M6 2.500h8.500L19 7v13.500a1.500 1.500 0 0 1-1.500 1.500h-11A1.500 1.500 0 0 1 5 20.500v-16A2 2 0 0 1 6 2.500Z" fill="#E2231A" />
    <path d="M14.500 2.500V7H19" fill="#F59A96" />
    <text x="12" y="17.500" textAnchor="middle" fontSize="6.200" fontWeight="800" fill="#fff" fontFamily="Arial, sans-serif">PDF</text>
  </S>
);
