import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { GateName, ProgressEvent, Project } from "./types";
import { LyricsPanel, PortraitPanel, AudioPanel, StoryboardPanel } from "./components";
import { StyleEditor } from "./StyleEditor";
import { ProgressPanel } from "./Progress";

const GATES: { key: GateName; label: string }[] = [
  { key: "lyrics", label: "歌词" },
  { key: "storyboard", label: "分镜" },
  { key: "portrait", label: "肖像" },
  { key: "audio", label: "音频" },
];

const STATUS_CN: Record<string, string> = {
  draft: "草稿", gathering: "收集确认中", composing: "合成中", done: "完成", failed: "失败",
};

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [cur, setCur] = useState<Project | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [pct, setPct] = useState(0);
  const [error, setError] = useState("");
  const [theme, setTheme] = useState("");
  const [lyricsText, setLyricsText] = useState("");
  const [targetSec, setTargetSec] = useState(180);
  const [autoApprove, setAutoApprove] = useState(false);
  const [creating, setCreating] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const refreshList = useCallback(() => {
    api.listProjects().then(setProjects).catch(() => {});
  }, []);

  const refreshCur = useCallback((id: string) => {
    api.getProject(id).then((p) => { setCur(p); setError(p.error); }).catch(() => {});
  }, []);

  useEffect(() => { refreshList(); }, [refreshList]);

  // 轻轮询：收集/合成阶段每 4s 刷新当前项目
  useEffect(() => {
    if (!cur || (cur.status !== "gathering" && cur.status !== "composing")) return;
    const t = setInterval(() => refreshCur(cur.id), 4000);
    return () => clearInterval(t);
  }, [cur, refreshCur]);

  // SSE
  useEffect(() => {
    esRef.current?.close();
    setEvents([]); setPct(0);
    if (!cur) return;
    const es = new EventSource(`/api/projects/${cur.id}/events`);
    es.onmessage = (m) => {
      try {
        const ev: ProgressEvent = JSON.parse(m.data);
        if (ev.stage === "end") { es.close(); refreshCur(cur.id); refreshList(); return; }
        setEvents((prev) => [...prev.slice(-200), ev]);
        setPct(ev.pct);
        if (ev.stage === "error") setError(ev.msg);
      } catch { /* ignore */ }
    };
    esRef.current = es;
    return () => es.close();
  }, [cur?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const create = async () => {
    if (!theme.trim() && !lyricsText.trim()) return;
    setCreating(true); setError("");
    try {
      const p = await api.createProject({
        theme: theme.trim(), lyrics_text: lyricsText.trim() || undefined,
        target_sec: targetSec, auto_approve: autoApprove,
      });
      setCur(p); refreshList();
    } catch (e) { setError(String(e)); }
    setCreating(false);
  };

  const act = async (fn: () => Promise<Project>) => {
    setError("");
    try { setCur(await fn()); refreshList(); } catch (e) { setError(String(e)); }
  };

  const open = (id: string) => {
    setEvents([]); setPct(0); setError("");
    api.getProject(id).then(setCur).catch(() => {});
  };

  const allApproved = cur && GATES.every((g) => cur.gates[g.key].approved_version != null);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <h1><span className="logo">E</span>EchoLoom</h1>
          <p>本地 AI MV 流水线 · Music3 → 分镜 → 对口型</p>
        </div>
        <div className="newproj">
          <label className="fld">主题（一句话）
            <input className="inp" value={theme} placeholder="例：深夜城市里独行的旅人"
              onChange={(e) => setTheme(e.target.value)} />
          </label>
          <label className="fld">或直接给歌词（可选）
            <textarea className="inp" rows={3} value={lyricsText} placeholder="[Verse]&#10;..."
              onChange={(e) => setLyricsText(e.target.value)} />
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            <label className="fld" style={{ flex: 1 }}>目标时长
              <select className="inp" value={targetSec} onChange={(e) => setTargetSec(+e.target.value)}>
                <option value={60}>60 秒</option>
                <option value={120}>120 秒</option>
                <option value={180}>3 分钟</option>
                <option value={300}>5 分钟（实验）</option>
              </select>
            </label>
            <label className="fld" style={{ flex: 1 }}>自动确认
              <select className="inp" value={autoApprove ? "1" : "0"}
                onChange={(e) => setAutoApprove(e.target.value === "1")}>
                <option value="0">每关人工确认</option>
                <option value="1">自动放行</option>
              </select>
            </label>
          </div>
          <button className="btn primary" disabled={creating || (!theme.trim() && !lyricsText.trim())}
            onClick={create}>
            {creating ? "创建中…" : "✦ 开始创作"}
          </button>
        </div>
        <div className="projlist">
          {projects.length === 0 && <div className="empty">还没有项目</div>}
          {projects.map((p) => (
            <button key={p.id} className={`projitem ${cur?.id === p.id ? "active" : ""}`} onClick={() => open(p.id)}>
              <span className="t"><span className={`dot ${p.status}`} />{p.title}</span>
              <span className="s">{STATUS_CN[p.status]} · {p.target_sec}s · {p.created_at.slice(5, 16)}</span>
            </button>
          ))}
        </div>
      </aside>

      <main className="main">
        <div className="pad">
          {!cur ? (
            <div className="hero">
              <h2>一句话，织出一支 <em>MV</em></h2>
              <p>
                EchoLoom 在你的显卡上完成全部创作：MiniMax Music3 作曲 → Z-Image 分镜 →
                MiniMax H3 图生视频 → FaceFusion 对口型 → Qwen3-ASR 字级对齐 karaoke 字幕 →
                ffmpeg 母带合成。四个关卡，每一步都由你确认。
              </p>
              <div className="steps">
                <span>① 歌词</span><span>② 分镜脚本</span><span>③ 歌手肖像</span>
                <span>④ 整曲试听</span><span>⑤ 一键合成</span>
              </div>
            </div>
          ) : (
            <>
              <div className="phead">
                <h2>{cur.title}</h2>
                <span className={`chip ${cur.status}`}>{STATUS_CN[cur.status]}</span>
                <span className="chip">seed {cur.seed}</span>
              </div>
              <div className="meta">
                主题「{cur.theme}」 · 目标 {cur.target_sec}s · {cur.language.toUpperCase()}
              </div>

              {error && (
                <div className="errbar">⚠ {error}
                  <button className="btn sm" onClick={() => setError("")}>知道了</button>
                </div>
              )}

              <div className="stepper">
                {GATES.map((g, i) => {
                  const gv = cur.gates[g.key];
                  const cls = gv.approved_version != null ? "approved" :
                    gv.versions.length ? "" : "";
                  return (
                    <button key={g.key} className={`step ${cls}`}
                      onClick={() => document.getElementById(`gate-${g.key}`)?.scrollIntoView({ behavior: "smooth" })}>
                      <span className="n">{gv.approved_version != null ? "✓" : i + 1}</span>
                      {g.label}
                      <span className="st">{gv.versions.length ? `v${gv.versions.length}` : "待生成"}</span>
                    </button>
                  );
                })}
                <div style={{ flex: 1 }} />
                <button className="btn ok" disabled={!allApproved || cur.status === "composing" || cur.status === "done"}
                  onClick={() => act(() => api.compose(cur.id, cur.ass_style))}>
                  {cur.status === "done" ? "✓ 已成片" : "▶ 合成最终 MV"}
                </button>
              </div>

              <div className="grid">
                <div>
                  <LyricsPanel proj={cur} act={act} />
                  <StoryboardPanel proj={cur} act={act} />
                  <PortraitPanel proj={cur} act={act} />
                  <AudioPanel proj={cur} act={act} />
                  {cur.final && (
                    <div className="panel">
                      <h3>🎬 成品</h3>
                      <p className="sub">烧录 karaoke 字幕的最终 MV</p>
                      <video className="final" src={cur.final} controls />
                      <div className="row">
                        <a className="dl" href={cur.final} download>⬇ 下载 MV</a>
                        {cur.master && <a className="dl" href={cur.master} download>⬇ 下载母带音频</a>}
                      </div>
                    </div>
                  )}
                </div>
                <div>
                  <ProgressPanel events={events} pct={pct} status={cur.status} />
                  <StyleEditor proj={cur} act={act} />
                </div>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
