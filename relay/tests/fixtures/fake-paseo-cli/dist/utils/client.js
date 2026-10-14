// Test double for the Paseo CLI internals osrelay/paseo-wake.mjs imports; driven by FAKE_PASEO_STATE.
import { appendFileSync, readFileSync } from "node:fs";

export async function connectToDaemon({ target }) {
  const state = JSON.parse(readFileSync(process.env.FAKE_PASEO_STATE, "utf8"));
  if (!state.connect) throw new Error("daemon down");
  if (target?.kind !== "instance") throw new Error("unexpected target");
  return {
    async fetchAgent({ agentId }) {
      return state.agents[agentId] ? { agent: state.agents[agentId] } : null;
    },
    async sendAgentMessage(agentId, text, options) {
      appendFileSync(process.env.FAKE_PASEO_LOG, JSON.stringify({ agentId, text, options }) + "\n");
    },
    async close() {},
  };
}
