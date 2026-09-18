import type { ProgressEvent } from "./types";

const STAGE_CN: Record<string, string> = {
  lyrics: "歌词", storyboard: "分镜", portrait: "肖像", audio: "作曲",
  compose: "合成", error: "错误", end: "结束", t2i: "生图", i2v: "图生视频",
};

export function ProgressPanel({ events, pct, status }: {
  events: ProgressEvent[]; pct: number; status: string;
}) {
  const R = 46;
  const C = 2 * Math.PI * R;
  const working = status === "composing" || pct > 0 && pct < 1;
  return (
    <div className="panel">
      <h3>📡 流水线进度</h3>
      <p className="sub">{working ? "GPU 工作中…" : status === "done" ? "已完成" : "等待任务"}</p>
      <div className="ring">
        <svg width="108" height="108">
          <circle cx="54" cy="54" r={R} stroke="rgba(255,255,255,.08)" strokeWidth="8" fill="none" />
          <circle cx="54" cy="54" r={R} stroke="var(--accent)" strokeWidth="8" fill="none"
            strokeDasharray={C} strokeDashoffset={C * (1 - pct)} strokeLinecap="round"
            style={{ transition: "stroke-dashoffset .6s ease" }} />
        </svg>
        <div className="pct">{Math.round(pct * 100)}%</div>
      </div>
      <div className="log">
        {events.length === 0 && <div className="ln" style={{ color: "var(--dim)" }}>暂无事件，提交任务后这里会实时滚动</div>}
        {events.map((e, i) => (
          <div key={i} className={`ln ${e.stage === "error" ? "err" : ""}`}>
            [<b>{STAGE_CN[e.stage] ?? e.stage}</b>] {e.msg}
          </div>
        ))}
      </div>
    </div>
  );
}
