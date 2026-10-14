// OSSLab Relay v1.4 wake helper (docs/specs/relay-v1.4.md): steer one message into a Paseo agent.
// Paseo's CLI `send` and MCP `send_agent_prompt` only interrupt a running turn; the client they are built on can
// steer, which ends a Codex native sleep without aborting the turn and starts a new turn when the agent is idle.
//   node paseo-wake.mjs check
//   node paseo-wake.mjs send <agent-id>   (message on stdin)
// Prints one JSON line. Exit 0 sent/ok, 1 Paseo or send failure, 2 usage or bad message, 3 agent not sendable now
// (missing, archived, or busy in an autonomous turn).
import { readFileSync, realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

const MAX_TEXT = 4000;

function result(value, exitCode) {
  return { value, exitCode };
}

function failure(code, message, exitCode = 1) {
  return result({ ok: false, code, message: String(message ?? "").slice(0, 300) }, exitCode);
}

function paseoRoot() {
  if (process.env.OSRELAY_PASEO_CLI) return process.env.OSRELAY_PASEO_CLI;
  for (const dir of (process.env.PATH ?? "").split(":")) {
    if (!dir) continue;
    try {
      // <package>/bin/paseo, usually reached through a symlink in ~/.local/bin.
      return dirname(dirname(realpathSync(join(dir, "paseo"))));
    } catch {
      // not in this PATH entry
    }
  }
  return null;
}

async function connect() {
  const root = paseoRoot();
  if (!root) throw Object.assign(new Error("paseo CLI not found on PATH"), { code: "paseo_unavailable" });
  try {
    // The same connection path `paseo send` uses: local daemon home, credentials and client id.
    const { connectToDaemon } = await import(pathToFileURL(join(root, "dist/utils/client.js")).href);
    const { selectDaemonTarget } = await import(pathToFileURL(join(root, "dist/utils/daemon-target.js")).href);
    return await connectToDaemon({ target: selectDaemonTarget({}, process.env, false) });
  } catch (error) {
    throw Object.assign(new Error(error?.message ?? String(error)), { code: "paseo_unavailable" });
  }
}

async function send(agentId) {
  const text = readFileSync(0, "utf8").trim();
  if (!text || text.length > MAX_TEXT || text.startsWith("/")) {
    return failure("invalid_message", "empty, too long, or starts with '/' (Paseo would interrupt)", 2);
  }
  const client = await connect();
  try {
    const found = await client.fetchAgent({ agentId });
    if (!found) return failure("agent_not_found", agentId, 3);
    // Sending to an archived agent would unarchive it and start a turn; a retired session is not a target.
    if (found.agent.archivedAt) return failure("agent_archived", agentId, 3);
    // A turn Paseo did not start (Codex /goal continuations are "autonomous-*") cannot take a steer: Paseo falls back
    // to replacing it, which aborts the running tool call (seen 2026-10-14). Leave it to the manager's own sleep loop.
    const turn = found.agent.activeTurn?.turnId ?? "";
    if (found.agent.status === "running" && turn.startsWith("autonomous-")) {
      return failure("agent_autonomous_turn", `${agentId} is in ${turn}`, 3);
    }
    await client.sendAgentMessage(found.agent.id, text, { activeTurnBehavior: "steer" });
    return result({ ok: true, status: found.agent.status ?? null }, 0);
  } finally {
    await client.close().catch(() => {});
  }
}

async function main(argv) {
  const [action, agentId] = argv;
  try {
    if (action === "check") {
      const client = await connect();
      await client.close().catch(() => {});
      return result({ ok: true }, 0);
    }
    if (action === "send" && agentId && argv.length === 2) return await send(agentId);
    return failure("usage", "usage: paseo-wake.mjs check | send <agent-id>", 2);
  } catch (error) {
    return failure(error?.code === "paseo_unavailable" ? "paseo_unavailable" : "send_failed", error?.message ?? error);
  }
}

const { value, exitCode } = await main(process.argv.slice(2));
process.stdout.write(JSON.stringify(value) + "\n");
process.exit(exitCode);
