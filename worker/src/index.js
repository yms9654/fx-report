/**
 * fx-report 익명 피드백 수신 → GitHub 이슈 생성
 *
 * 필요한 것
 *   secret GH_TOKEN   : yms9654/fx-report 의 Issues 쓰기 권한 fine-grained PAT
 *   var    GH_REPO    : "owner/repo"
 *   var    ALLOW_ORIGIN: 페이지 오리진
 *   kv     RL         : (선택) 레이트리밋용. 없으면 레이트리밋 생략
 */

const KINDS = ["도움됨", "안맞음", "제안", "오류"];
const MAX_TEXT = 2000;
const MAX_CTX = 40;
const RL_MAX = 5;              // IP 당
const RL_WINDOW = 3600;        // 초

const j = (obj, status, origin) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": origin,
      "vary": "origin",
    },
  });

/** 이슈 본문에 그대로 들어가므로 태그를 무력화한다 */
const clean = (v, max) =>
  String(v ?? "").slice(0, max).replace(/[<>]/g, (c) => ({ "<": "&lt;", ">": "&gt;" }[c])).trim();

async function hash(s) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(b)].slice(0, 6).map((x) => x.toString(16).padStart(2, "0")).join("");
}

async function rateLimited(env, ip) {
  if (!env.RL) return false;                       // KV 미설정이면 통과
  const key = "rl:" + (await hash(ip + (env.SALT || "fx")));
  const n = parseInt((await env.RL.get(key)) || "0", 10);
  if (n >= RL_MAX) return true;
  await env.RL.put(key, String(n + 1), { expirationTtl: RL_WINDOW });
  return false;
}

export default {
  async fetch(request, env) {
    const origin = env.ALLOW_ORIGIN || "*";

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": origin,
          "access-control-allow-methods": "POST, OPTIONS",
          "access-control-allow-headers": "content-type",
          "access-control-max-age": "86400",
        },
      });
    }
    if (request.method !== "POST") return j({ ok: false, error: "POST only" }, 405, origin);

    let p;
    try {
      p = await request.json();
    } catch {
      return j({ ok: false, error: "본문을 읽지 못했습니다." }, 400, origin);
    }

    // 허니팟 — 봇만 채우는 필드. 채워져 있으면 성공한 척하고 버린다.
    if (p.website) return j({ ok: true, dropped: true }, 200, origin);

    const kind = KINDS.includes(p.kind) ? p.kind : null;
    if (!kind) return j({ ok: false, error: "유형이 올바르지 않습니다." }, 400, origin);

    const text = clean(p.text, MAX_TEXT);
    const ip = request.headers.get("cf-connecting-ip") || "0.0.0.0";
    if (await rateLimited(env, ip)) {
      return j({ ok: false, error: "잠시 후 다시 시도해 주세요. (시간당 5건)" }, 429, origin);
    }

    const rows = Array.isArray(p.ctx)
      ? p.ctx.slice(0, 10).map(([k, v]) => `| ${clean(k, MAX_CTX)} | ${clean(v, MAX_CTX)} |`).join("\n")
      : "";

    const first = text.split("\n")[0].slice(0, 50);
    const title = `[${kind}] ${first || clean(p.date, 20) + " 리포트"}`;
    const body = [
      text || "_(내용 없음)_",
      "",
      "---",
      "",
      "<details><summary>제출 시점 정보</summary>",
      "",
      "| 항목 | 값 |",
      "|---|---|",
      rows,
      `| 화면폭 | ${clean(p.width, 10)}px |`,
      `| 국가 | ${clean(request.cf?.country, 4) || "?"} |`,
      "",
      "</details>",
      "",
      "<sub>페이지 피드백 폼에서 익명으로 접수되었습니다.</sub>",
    ].join("\n");

    const r = await fetch(`https://api.github.com/repos/${env.GH_REPO}/issues`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${env.GH_TOKEN}`,
        accept: "application/vnd.github+json",
        "content-type": "application/json",
        "user-agent": "fx-report-feedback-worker",
      },
      body: JSON.stringify({ title, body, labels: [kind, "익명"] }),
    });

    if (!r.ok) {
      return j({ ok: false, error: `GitHub 등록 실패 (${r.status})` }, 502, origin);
    }
    const issue = await r.json();
    return j({ ok: true, number: issue.number, url: issue.html_url }, 200, origin);
  },
};
