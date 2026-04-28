import nextConfig from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// eslint-plugin-react doesn't support ESLint 9 flat config API (getFilename removed)
// Drop the react plugin config entry; keep next/typescript and @next/next rules
const filtered = [...nextConfig, ...nextTs].filter(
  (c) => !c.plugins?.react
);

export default filtered;
