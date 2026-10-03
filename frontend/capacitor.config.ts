import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.unicplaquiste.ai",
  appName: "UniC AI",
  webDir: "dist",
  android: {
    adjustMarginsForEdgeToEdge: "force",
    allowMixedContent: false, // https uniquement
  },
  plugins: {
    SplashScreen: { launchShowDuration: 0 },
    StatusBar: { style: "DARK", backgroundColor: "#1A2320" },
  },
};

export default config;
