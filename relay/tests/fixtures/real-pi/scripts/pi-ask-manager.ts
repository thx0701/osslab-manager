/**
 * osslab-manager pi 工人的「問經理」工具（Relay v1.3 問答通道）。
 *
 * 工人碰到要經理拍板的事時呼叫 ask_manager 並暫停。題目以對話框送出：RPC 模式的 pi 把它交給
 * pi-worker-driver.py，驅動程式經 Relay 登記、等經理 `osrelay answer`，再把答案寫回 pi 的 stdin。
 * 工人與它開的 bash 碰不到這條回寫通道，不能自己回答自己。
 *
 * 只有驅動程式確認有 Relay 通道時才給 pi `OSLAB_ASK_CHANNEL=1`；沒有就立刻回「沒有經理通道」（手動派工同）。
 * 逾時由 pi 端對話框計時；常數只在這裡，pi 會把它帶進對話框請求，驅動程式原樣轉給 Relay 算 deadline。
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

// 12 分鐘：短於 Relay 的 900 秒靜默警報，工人等答案時不會誤觸警報。
const TIMEOUT_MS = 720_000;
const MAX_QUESTIONS = 3;
const NO_CHANNEL = "本次派工沒有經理通道：照原規則停下受影響的部分、寫進回執，繼續做不受影響的部分，不要重試。";
const NO_ANSWER = "沒有收到經理回覆（逾時或通道中斷）：照原規則停下受影響的部分、寫進回執，繼續做不受影響的部分，不要重試。";
const LIMIT = `本輪已達發問上限 ${MAX_QUESTIONS} 題：照原規則停下受影響的部分、寫進回執，不要再發問。`;

export default function askManager(pi: ExtensionAPI) {
	let asked = 0;
	pi.registerTool({
		name: "ask_manager",
		label: "Ask manager",
		description: [
			"向派工經理發問並暫停，等經理回覆後在同一輪接著做。只在三種情況使用：",
			"工單允許的檔案範圍與實際需要衝突（scope_conflict）；契約或既有測試與工單衝突（contract_conflict）；",
			"工單寫得模糊、無法判斷預期結果（ambiguous_ticket）。",
			"事實自己查，不要問。不可逆操作、production、秘密一律不准問，經理回答了也照舊禁止。",
			`每輪最多 ${MAX_QUESTIONS} 題。收到「沒有經理通道」「沒有收到經理回覆」或「已達發問上限」時，`,
			"照原規則停下受影響的部分、寫進回執，繼續做其他部分，不要重試。",
			"經理的回覆視為工單補充；回執的問答段逐題列出題目、回覆或逾時、你照回覆做了什麼。",
		].join(""),
		parameters: Type.Object({
			kind: Type.Enum(["scope_conflict", "contract_conflict", "ambiguous_ticket"], {
				description: "scope_conflict 範圍衝突｜contract_conflict 契約衝突｜ambiguous_ticket 工單模糊",
			}),
			where: Type.String({ minLength: 1, description: "卡在哪：檔案路徑或工單條款，附必要證據" }),
			options: Type.Array(Type.String({ minLength: 1 }), {
				minItems: 2,
				maxItems: 3,
				description: "2 到 3 個可行選項",
			}),
			recommendation: Type.String({ minLength: 1, description: "你建議選哪個，附一句理由" }),
			impact: Type.String({ minLength: 1, description: "不回答的話，哪些部分會停下" }),
		}),
		// 同一則回覆的多個發問依序執行：一次只等一題，上限計數不會競態。
		executionMode: "sequential",
		async execute(toolCallId, params, _signal, _onUpdate, ctx) {
			const reply = (text: string) => ({ content: [{ type: "text" as const, text }], details: undefined });
			if (process.env.OSLAB_ASK_CHANNEL !== "1" || ctx.mode !== "rpc") return reply(NO_CHANNEL);
			if (asked >= MAX_QUESTIONS) return reply(LIMIT);
			asked += 1;
			// 標題帶 toolCallId：對話框只有標題與提示兩欄，驅動程式靠它從事件流找回這次呼叫的完整參數。
			const answer = await ctx.ui.input(`osslab-ask:${toolCallId}`, params.where.slice(0, 200), {
				timeout: TIMEOUT_MS,
			});
			if (answer === undefined || answer.trim() === "") return reply(NO_ANSWER);
			return reply(`經理回覆（視為工單補充，以 Relay 事件為正本）：${answer}`);
		},
	});
}
