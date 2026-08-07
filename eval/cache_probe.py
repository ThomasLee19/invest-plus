"""前缀缓存命中探针 —— A/B 对照的主实验。

为什么这是主实验而不是延迟评测
------------------------------
`cached_tokens` 是上游直接返回的确定整数，不受网络抖动、时段、上游负载影响，需要的
样本量是个位数。而首次反馈延迟的待测效应量级只有百毫秒（前缀缓存省的是 prefill，
而 `_llm_json` 是非流式调用，两次完整 decode 才是延迟主体），噪声却与效应同量级。
把结论押在几百次带噪声的墙钟采样上，不如押在十次确定性观测上。

本脚本刻意**完整消费整条 SSE 流**，不做提前断开。提前断开看似省时间，实则停不掉
后端：`chat_rt.py` 的 `/chat` 是同步 def，`stream()` 是同步生成器，Starlette 把它丢进
线程池逐项拉取，全文没有 `is_disconnected()` 检查，客户端断连只在生成器下一次 yield
时才被察觉——而对有工具的问题，下一次 yield 在整个 Act + Reflect 之后。于是"省下"的
时间会变成后台重叠，污染下一次测量并让日志归属错位。只发十次请求，等得起。

实验序列
--------
    [可选 --cold-wait]  等待超过上游缓存 TTL，制造真正的冷启动
    X1 X2 X3            同一道题连发三次
    Y1 Y2               换一道内容完全不同的题，再发两次

判读（按 stage 分别看，classify_skill 与 plan 的静态前缀长度不同，可能一个命中一个不中）：

    改前版本（变量夹在静态内容中间）
        期望全程 cached_tokens == 0。稳定前缀只有几十 token，低于上游最小可缓存长度。

    改后版本（静态前缀整体前置到 system message）
        X1 可能为 0（真冷启动），X2/X3 应该 > 0。
        **Y1 是关键**：Y 与 X 内容完全不同，若 Y1 的 cached_tokens 依然 > 0，说明命中的
        是跨查询共享的静态前缀，而不是"同一道题问了两遍"。这一条才是这次改造的卖点，
        也是按题分组的延迟评测永远证明不了的东西。

前提
----
    docker compose up -d          # ES + Postgres
    cd backend/app && PYTHONUNBUFFERED=1 PYTHONPATH=. \
        uvicorn app_main:app --port 8000 > /tmp/investplus-backend.log 2>&1

用法
----
    python eval/cache_probe.py --label before --backend-log /tmp/investplus-backend.log
    # git 切到改后版本，重启后端，换一个日志文件
    python eval/cache_probe.py --label after  --backend-log /tmp/investplus-backend-after.log

产出
----
    eval/cache_probe_{label}.json / .md
"""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8000"

# 与后端 _log_cache_usage() 的输出格式对应。cached_tokens 取不到时后端打字面量 None，
# 这里解析成 Python None 并与 0 严格区分：「字段名不对」和「确实没命中」是两个结论。
_CACHE_RE = re.compile(
    r"\[llm_cache\] stage=(?P<stage>\S+) "
    r"prompt_tokens=(?P<prompt>\S+) "
    r"cached_tokens=(?P<cached>\S+) "
    r"completion_tokens=(?P<completion>\S+)"
)
# agent_plan / classify_skill 吞掉 LLM 异常后会打这些行。命中说明该次请求走了降级路径，
# 它的 usage 数据不能与正常请求混在一起解读。
_DEGRADED_RE = re.compile(r"\[(agent_plan|classify_skill|should_continue)\] .*(失败|降级)")

DEFAULT_Q_X = "苹果公司最近的财报里有哪些值得关注的风险因素？"
DEFAULT_Q_Y = "微软云最近一个季度的营收表现如何？"


def _maybe_int(raw: str):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _read_since(path: str, offset: int) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        return f.read()


def _file_size(path: str) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def wait_for_quiet(path: str, quiet_seconds: float, timeout: float) -> bool:
    """等到后端日志连续 quiet_seconds 秒没有新增内容。

    这是「请求真正串行」的唯一可靠保证。返回 False 表示等到超时仍未安静，
    此时后续测量已不可信，调用方应当记录这一事实而不是假装无事发生。
    """
    deadline = time.monotonic() + timeout
    last_size = _file_size(path)
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(0.5)
        size = _file_size(path)
        if size != last_size:
            last_size = size
            stable_since = time.monotonic()
        elif time.monotonic() - stable_since >= quiet_seconds:
            return True
    return False


def create_session() -> str:
    resp = requests.post(f"{BASE_URL}/create_session", timeout=30)
    resp.raise_for_status()
    return resp.json()["session_id"]


def fire(question: str, read_timeout: float) -> dict:
    """完整消费一条 SSE 流直到 [DONE]，不提前断开。"""
    session_id = create_session()
    t0 = time.monotonic()
    first_event = None
    events = 0
    tools = []
    try:
        resp = requests.post(
            f"{BASE_URL}/chat",
            params={"session_id": session_id},
            json={"message": question},
            stream=True,
            timeout=read_timeout,
        )
        if resp.status_code != 200:
            return {"ok": False, "error": f"http {resp.status_code}", "elapsed": None,
                    "first_feedback": None, "events": 0, "plan_tools": []}
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            if first_event is None:
                first_event = time.monotonic() - t0
            events += 1
            payload = line[len("data: "):]
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("role") == "agent":
                m = re.search(r"(?:正在调用|补充调用) (\w+):", data.get("content", ""))
                if m:
                    tools.append(m.group(1))
        return {"ok": True, "error": None, "elapsed": time.monotonic() - t0,
                "first_feedback": first_event, "events": events, "plan_tools": tools}
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "elapsed": time.monotonic() - t0, "first_feedback": first_event,
                "events": events, "plan_tools": tools}


def probe_once(tag: str, question: str, args) -> dict:
    offset = _file_size(args.backend_log)
    result = fire(question, args.read_timeout)
    quiet = wait_for_quiet(args.backend_log, args.quiet_seconds, args.quiet_timeout)
    chunk = _read_since(args.backend_log, offset)

    calls = [{
        "stage": m.group("stage"),
        "prompt_tokens": _maybe_int(m.group("prompt")),
        "cached_tokens": _maybe_int(m.group("cached")),
        "completion_tokens": _maybe_int(m.group("completion")),
    } for m in _CACHE_RE.finditer(chunk)]

    rec = {
        "tag": tag,
        "question": question,
        "wall_clock": time.strftime("%Y-%m-%d %H:%M:%S"),
        "backend_quiet": quiet,
        "degraded": bool(_DEGRADED_RE.search(chunk)),
        "llm_calls": calls,
        **result,
    }
    marks = " ".join(
        f"{c['stage']}:cached={c['cached_tokens']}/prompt={c['prompt_tokens']}"
        f",out={c['completion_tokens']}"
        for c in calls
    ) or "(无 llm_cache 日志)"
    flags = []
    if not quiet:
        flags.append("后端未静默")
    if rec["degraded"]:
        flags.append("走了降级路径")
    if not result["ok"]:
        flags.append(result["error"])
    print(f"  {tag:<4} {marks}{'  [' + ', '.join(flags) + ']' if flags else ''}")
    return rec


def _backend_commit() -> str | None:
    """记录被测 agent.py 的版本指纹，让两份产物能自证跑的是不同代码。

    不能只用 `HEAD` + `dirty` 标记：A/B 最自然的做法就是改一版不提交跑 after、
    `git stash` 回去跑 before，这条路径下两侧 HEAD 相同、两侧都 dirty，字段完全一致，
    看起来像做过校验其实什么也没区分。所以附上文件内容的 blob 哈希，它对内容敏感。
    """
    try:
        root = Path(__file__).resolve().parent.parent
        target = "backend/app/service/agent/agent.py"
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10)
        blob = subprocess.run(["git", "-C", str(root), "hash-object", target],
                              capture_output=True, text=True, timeout=10)
        if head.returncode != 0 or blob.returncode != 0:
            return None
        return f"{head.stdout.strip()}@agent.py:{blob.stdout.strip()[:12]}"
    except Exception:
        return None


def verdict(records: list[dict]) -> dict:
    """按 stage 归纳命中情况，并单独判定跨题共享是否成立。

    两个量必须分开，否则会得出反向结论：

    `series` 取每条请求的**第一次**调用。只有它反映跨请求的前缀缓存，也只有它能拿去做
    A/B 对照。

    `within_request` 列出该 stage 的每一次调用。reflect 一条请求内会调用多轮，每轮把新
    memory 追加进 prompt，于是第 2 轮天然与第 1 轮共享一大段前缀——那是**请求内**的前缀
    复用，改造前的代码同样存在。把它当成本次改造的效果（比如对多次调用取 max）会凭空
    造出巨额命中，让 A/B 失去意义。所以它单独记录、单独呈现，不参与判定。

    判定的认识论前提：厂商文档明确「即使请求上下文完全一致，仍可能未命中，具体命中概率
    由系统判定」。因此**命中是有信息的**（不可能命中一段不可缓存的前缀），**未命中是没有
    信息的**（可能只是这次被路由到了没有该前缀的实例）。所有分支据此设置，未命中一律不
    输出 False 这种确定性结论。
    """
    stages = sorted({c["stage"] for r in records for c in r["llm_calls"]})
    out = {}
    for stage in stages:
        series, within = [], []
        for r in records:
            calls = [c for c in r["llm_calls"] if c["stage"] == stage]
            series.append({"tag": r["tag"], "present": bool(calls),
                           **(calls[0] if calls else {})})
            for i, c in enumerate(calls):
                within.append({"tag": r["tag"], "round": i + 1, **c})

        present = [s for s in series if s["present"]]
        known = [s["cached_tokens"] for s in present if s.get("cached_tokens") is not None]
        hits = [v for v in known if v > 0]
        y = next((s for s in series if s["tag"] == "Y1"), None)

        if not present:
            state, cross = "本轮未触发该阶段（题目 X/Y 都没走到这一步），无数据", None
        elif not known:
            state, cross = ("字段缺失：usage 里没有可识别的缓存字段，"
                            "去后端日志找那行完整 usage 对象比对字段名"), None
        elif y is None or not y["present"]:
            # 上一版在这里直接落进 else 判成「跨题共享不成立」，把整个改造的卖点判反了。
            state, cross = ("Y 侧未触发该阶段，无法判定跨题共享"
                            + ("；X 侧有命中，说明该阶段前缀本身可缓存" if hits
                               else "；X 侧亦未命中")), None
        elif not hits:
            state, cross = ("未观测到命中。注意厂商文档声明命中率非 100%，"
                            "未命中不构成「前缀不可缓存」的证据，只能说明样本内没看到"), None
        elif y.get("cached_tokens"):
            state, cross = "命中，且跨题共享成立（Y 与 X 内容无关仍命中同一前缀）", True
        else:
            state, cross = ("X 侧命中、Y 侧未命中。受上游命中随机性影响，"
                            "本样本量不足以判定跨题共享，需增加 Y 侧重复次数"), None

        out[stage] = {
            "series": series,
            "within_request": within,
            "state": state,
            "cross_question_hit": cross,
            "hit_count": len(hits),
            "observed_count": len(known),
            "prompt_tokens": next((s.get("prompt_tokens") for s in present
                                   if s.get("prompt_tokens") is not None), None),
        }
    return out


def write_report(result: dict, path: Path):
    L = [f"# 前缀缓存命中探针 — {result['label']}\n"]
    L.append(f"被测 commit：`{result['backend_commit'] or '未知'}` ｜ "
             f"运行于 {result['started_at']} ｜ 冷启动等待 {result['cold_wait']}s\n")
    L.append("本脚本完整消费每条 SSE 流后再等后端日志静默，因此请求之间不存在重叠，"
             "`[llm_cache]` 行按字节偏移归属是精确的。\n")

    L.append("\n## 各阶段命中序列\n")
    L.append("下表只取每条请求的**第一次**调用。这是唯一反映跨请求前缀缓存、"
             "也是唯一可用于 A/B 对照的量。\n")
    for stage, v in result["verdict"].items():
        L.append(f"\n### `{stage}`（首次调用 prompt 约 {v['prompt_tokens']} token）\n")
        L.append("| 请求 | 是否触发 | cached_tokens | prompt_tokens | completion_tokens |")
        L.append("| --- | --- | --- | --- | --- |")
        for s in v["series"]:
            if not s["present"]:
                L.append(f"| {s['tag']} | 否 | — | — | — |")
            else:
                L.append(f"| {s['tag']} | 是 | {s.get('cached_tokens')} | "
                         f"{s.get('prompt_tokens')} | {s.get('completion_tokens')} |")
        L.append(f"\n观测 {v['observed_count']} 次，命中 {v['hit_count']} 次。")
        L.append(f"\n**判定：{v['state']}**\n")
        if len(v["within_request"]) > len(v["series"]):
            L.append(f"\n<details><summary>{stage} 的请求内全部调用"
                     f"（{len(v['within_request'])} 次）</summary>\n")
            L.append("\n| 请求 | 轮次 | cached_tokens | prompt_tokens | completion_tokens |")
            L.append("| --- | --- | --- | --- | --- |")
            for w in v["within_request"]:
                L.append(f"| {w['tag']} | {w['round']} | {w['cached_tokens']} | "
                         f"{w['prompt_tokens']} | {w['completion_tokens']} |")
            L.append("\n第 2 轮起的命中来自**请求内**的前缀复用：每轮把新 memory 追加进 "
                     "prompt，后一轮天然以前一轮为前缀。改造前的代码同样有这个现象，"
                     "因此这些数字**不能**用来支持本次改造的效果，也不可参与 A/B。\n")
            L.append("</details>\n")

    L.append("\n## 请求明细\n")
    L.append("| 请求 | 事件数 | 首次反馈 | 全程耗时 | Plan 工具 | 后端静默 | 降级 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- |")
    for r in result["records"]:
        ff = f"{r['first_feedback']:.2f}s" if r["first_feedback"] is not None else "N/A"
        el = f"{r['elapsed']:.1f}s" if r["elapsed"] is not None else "N/A"
        L.append(f"| {r['tag']} | {r['events']} | {ff} | {el} | "
                 f"{','.join(r['plan_tools']) or '-'} | "
                 f"{'是' if r['backend_quiet'] else '**否**'} | "
                 f"{'**是**' if r['degraded'] else '否'} |")
    L.append("\n首次反馈与全程耗时仅作参考。样本量是个位数，且完整消费流的执行方式与"
             "延迟评测不同，这两列不能拿来做 A/B 延迟比较。\n")

    L.append("\n## 怎么读这份报告\n")
    L.append("- `Y1` 那一行是关键。Y 与 X 内容完全不同，Y1 仍然命中才说明复用的是"
             "跨查询共享的静态前缀。\n")
    L.append("- `cached_tokens` 为 `None` 表示字段名取不到，与 `0`（确实没命中）是两回事。\n")
    L.append("- 任何一行「后端静默＝否」或「降级＝是」，该行数据都要排除后重跑。\n")
    path.write_text("\n".join(L), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description="前缀缓存命中探针")
    p.add_argument("--label", required=True, help="before / after")
    p.add_argument("--backend-log", required=True, help="后端 stdout 日志路径（必需）")
    p.add_argument("--question-x", default=DEFAULT_Q_X)
    p.add_argument("--question-y", default=DEFAULT_Q_Y,
                   help="必须与 X 内容完全不同，用于检验跨题共享")
    p.add_argument("--repeats-x", type=int, default=3)
    p.add_argument("--repeats-y", type=int, default=2)
    p.add_argument("--cold-wait", type=float, default=0.0,
                   help="开跑前静置秒数，用于让上游缓存 TTL 过期制造真冷启动")
    p.add_argument("--quiet-seconds", type=float, default=3.0)
    p.add_argument("--quiet-timeout", type=float, default=300.0)
    p.add_argument("--read-timeout", type=float, default=120.0)
    args = p.parse_args()

    if not Path(args.backend_log).exists():
        raise SystemExit(f"后端日志不存在：{args.backend_log}\n"
                         f"请按 docstring 里的命令重定向 uvicorn 的 stdout。")

    started = time.strftime("%Y-%m-%d %H:%M:%S")
    commit = _backend_commit()
    print(f"label={args.label}  commit={commit}  开始于 {started}")

    if args.cold_wait > 0:
        print(f"冷启动等待 {args.cold_wait}s（让上游缓存 TTL 过期）…")
        time.sleep(args.cold_wait)

    records = []
    print(f"\n题目 X：{args.question_x}")
    for i in range(args.repeats_x):
        records.append(probe_once(f"X{i+1}", args.question_x, args))
    print(f"\n题目 Y（内容与 X 无关）：{args.question_y}")
    for i in range(args.repeats_y):
        records.append(probe_once(f"Y{i+1}", args.question_y, args))

    result = {
        "label": args.label,
        "backend_commit": commit,
        "started_at": started,
        "cold_wait": args.cold_wait,
        "question_x": args.question_x,
        "question_y": args.question_y,
        "records": records,
        "verdict": verdict(records),
    }

    out_json = Path(__file__).parent / f"cache_probe_{args.label}.json"
    out_md = Path(__file__).parent / f"cache_probe_{args.label}.md"
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(result, out_md)

    print("\n判定：")
    for stage, v in result["verdict"].items():
        print(f"  {stage:<16} 观测{v['observed_count']}次/命中{v['hit_count']}次  {v['state']}")
    print(f"\n{out_json}\n{out_md}")

    # 一条 [llm_cache] 都没匹配到时，整个实验的前提就不成立：可能日志路径给错、
    # 忘了 PYTHONUNBUFFERED=1、或上游改了 usage 字段名导致日志格式变化。此时静默
    # 写出一份没有任何 stage 小节的报告是最坏的结果，直接非零退出。
    if not result["verdict"]:
        raise SystemExit(
            "未从日志中解析到任何 [llm_cache] 行。请检查：--backend-log 路径是否正确；"
            "后端是否以 PYTHONUNBUFFERED=1 启动；agent.py 是否包含 _log_cache_usage 埋点。")


if __name__ == "__main__":
    main()
