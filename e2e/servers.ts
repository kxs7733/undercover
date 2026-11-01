// The servers the end-to-end tests run on ports of their own, so they never touch
// the ones `npm run dev` starts: the backend, the dashboard, and the stand-ins
// for the agent, the Copilot, Supabase Auth and the judge.
export const BACKEND = "http://127.0.0.1:8001";
export const DASHBOARD = "http://localhost:5174";
export const AGENT_STAND_IN = "http://127.0.0.1:8003";
export const AUTH_STAND_IN = "http://127.0.0.1:8004";
export const JUDGE_STAND_IN = "http://127.0.0.1:8005";
export const COPILOT_STAND_IN = "http://127.0.0.1:8007";
// Nothing listens here: the page's end-to-end tests see the Auditor not running.
export const NO_AUDITOR = "http://127.0.0.1:8009";

// The test backend's API key for the agent's side, and the header that carries it.
export const AGENT_KEY = "e2e-agent-key-0123456789abcdefghijklmnopq";
export const AGENT_KEY_HEADERS = { "X-API-Key": AGENT_KEY };
