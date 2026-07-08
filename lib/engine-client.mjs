// 엔진(Python 사이드카) NDJSON 클라이언트 + per-chat 직렬화 뮤텍스.
//
// 2차 리뷰 하드닝 반영:
// - idle 타임아웃: heartbeat 포함 어떤 이벤트든 IDLE_TIMEOUT_MS 동안 없으면 중단
// - 전체 데드라인: TOTAL_DEADLINE_MS (기본 8분)
// - per-chat 뮤텍스: layer 스트리밍 쓰기와 노트 질문 쓰기의 경합 차단

const ENGINE_URL = process.env.ENGINE_URL || "http://127.0.0.1:8801";
const IDLE_TIMEOUT_MS = Number(process.env.ENGINE_IDLE_TIMEOUT_MS || 30_000);
const TOTAL_DEADLINE_MS = Number(process.env.ENGINE_TOTAL_DEADLINE_MS || 8 * 60_000);

// ---------------------------------------------------------------- mutex

const chatLocks = new Map(); // chatId → Promise (체인 꼬리)

export function withChatLock(chatId, fn) {
  const tail = chatLocks.get(chatId) || Promise.resolve();
  const next = tail.then(fn, fn); // 앞 작업 실패해도 체인 유지
  chatLocks.set(
    chatId,
    next.catch(() => {}),
  );
  return next;
}

// ---------------------------------------------------------------- client

export async function engineHealthz() {
  const res = await fetch(`${ENGINE_URL}/healthz`, { signal: AbortSignal.timeout(5_000) });
  if (!res.ok) throw new Error(`engine healthz ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------- cancel

const activeRuns = new Map(); // chat_id → AbortController (사용자 중지 버튼용)

/** 진행 중인 엔진 런을 중단. 요청이 끊기면 엔진 쪽도 워크플로를 취소한다. */
export function cancelEngineRun(chatId) {
  const controller = activeRuns.get(chatId);
  if (!controller) return false;
  controller.abort(new Error("사용자가 생성을 중단했습니다."));
  return true;
}

/**
 * POST /v1/answer 후 NDJSON 스트림 소비.
 * handlers: { onLayer(layer), onProgress(p), onFinal(final) } — 각 이벤트마다 await.
 * final을 못 받고 스트림이 끝나면 throw (기존 failed 경로로 흘러감).
 */
export async function runEngineAnswer(request, handlers = {}) {
  const controller = new AbortController();
  if (request.chat_id) activeRuns.set(request.chat_id, controller);
  const totalTimer = setTimeout(
    () => controller.abort(new Error("엔진 전체 데드라인 초과")),
    TOTAL_DEADLINE_MS,
  );
  let idleTimer = null;
  const resetIdle = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(
      () => controller.abort(new Error("엔진 응답 없음 (idle 타임아웃)")),
      IDLE_TIMEOUT_MS,
    );
  };

  let sawFinal = false;
  try {
    resetIdle();
    const res = await fetch(`${ENGINE_URL}/v1/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    if (!res.ok || !res.body) {
      throw new Error(`엔진 응답 오류 (${res.status})`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      resetIdle();
      buffer += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        const event = JSON.parse(line);
        if (event.type === "heartbeat") continue;
        if (event.type === "layer") {
          await handlers.onLayer?.(event);
        } else if (event.type === "progress") {
          await handlers.onProgress?.(event);
        } else if (event.type === "final") {
          sawFinal = true;
          await handlers.onFinal?.(event);
        } else if (event.type === "error") {
          throw new Error(event.message || "엔진 내부 오류");
        }
      }
    }
    if (!sawFinal) {
      throw new Error("엔진 스트림이 최종 답변 없이 종료됐습니다.");
    }
  } catch (error) {
    // abort 사유(데드라인/idle)를 원인 메시지로 승격
    if (controller.signal.aborted && controller.signal.reason instanceof Error) {
      throw controller.signal.reason;
    }
    throw error;
  } finally {
    clearTimeout(totalTimer);
    if (idleTimer) clearTimeout(idleTimer);
    if (request.chat_id && activeRuns.get(request.chat_id) === controller) {
      activeRuns.delete(request.chat_id);
    }
  }
}
