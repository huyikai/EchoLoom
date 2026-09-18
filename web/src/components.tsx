import { useState } from "react";
import { api } from "./api";
import type { Project, Shot } from "./types";

type Act = (fn: () => Promise<Project>) => void;

function VersionBar({ versions, approved, onView, onSelect }: {
  versions: { id: number }[];
  approved: number | null;
  onView: (id: number) => void;
  onSelect: (id: number) => void;
}) {
  if (!versions.length) return null;
  const [sel, setSel] = useState(versions[versions.length - 1].id);
  return (
    <div className="verbar">
      {versions.map((v) => (
        <button key={v.id}
          className={`verbtn ${sel === v.id ? "sel" : ""}`}
          onClick={() => { setSel(v.id); onView(v.id); }}>
          v{v.id}{approved === v.id && <span className="okmark">✓已确认</span>}
        </button>
      ))}
      {approved != null && approved !== sel && (
        <button className="verbtn" onClick={() => { setSel(approved); onSelect(approved); }}>看已确认版</button>
      )}
    </div>
  );
}

export function LyricsPanel({ proj, act }: { proj: Project; act: Act }) {
  const g = proj.gates.lyrics;
  const [view, setView] = useState<number | null>(g.approved_version ?? g.versions.at(-1)?.id ?? null);
  const [draft, setDraft] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const v = g.versions.find((x) => x.id === view) ?? g.versions.at(-1);
  const isApproved = g.approved_version != null;

  return (
    <div className="panel" id="gate-lyrics">
      <h3>✎ 歌词 {isApproved && <span className="badge ok">已确认 v{g.approved_version}</span>}</h3>
      <p className="sub">分段标签结构（[Verse]/[Chorus]…），可直接编辑后存为新版本</p>
      <VersionBar versions={g.versions} approved={g.approved_version}
        onView={setView} onSelect={(id) => { setView(id); setDraft(null); }} />
      {v ? (
        <>
          <textarea className="lyrics" value={draft ?? v.text ?? ""} onChange={(e) => setDraft(e.target.value)} />
          <div className="row">
            <button className="btn primary" disabled={!isApproved || draft == null || draft === v.text}
              onClick={() => draft && act(async () => {
                try { return await api.editLyrics(proj.id, draft); }
                catch (e) { setErr(String(e)); throw e; }
              })}>保存为新版本</button>
            <div className="spacer" />
            <button className="btn" disabled={proj.status !== "gathering" && proj.status !== "draft"}
              onClick={() => act(() => api.regenerate(proj.id, "lyrics"))}>↻ 重新生成</button>
            <button className="btn ok" disabled={isApproved}
              onClick={() => act(() => api.approve(proj.id, "lyrics", view ?? undefined))}>
              ✓ 确认此版本
            </button>
          </div>
          {err && <div className="row" style={{ color: "var(--danger)" }}>{err}</div>}
        </>
      ) : <div className="empty">生成中…</div>}
    </div>
  );
}

export function StoryboardPanel({ proj, act }: { proj: Project; act: Act }) {
  const g = proj.gates.storyboard;
  const [view, setView] = useState<number | null>(g.approved_version ?? g.versions.at(-1)?.id ?? null);
  const [showCaption, setShowCaption] = useState(false);
  const v = g.versions.find((x) => x.id === view) ?? g.versions.at(-1);
  const sb = v?.storyboard;
  const isApproved = g.approved_version != null;
  const total = sb?.shots?.reduce((s: number, x: Shot) => s + (x.duration || 0), 0) ?? 0;

  return (
    <div className="panel" id="gate-storyboard">
      <h3>🎞 分镜脚本 {isApproved && <span className="badge ok">已确认 v{g.approved_version}</span>}</h3>
      <p className="sub">
        {sb?.shots?.length ?? 0} 个镜头 · 约 {total.toFixed(0)}s ·
        歌手形象：<span style={{ color: "var(--muted)" }}>{sb?.singer_desc?.slice(0, 80)}…</span>
      </p>
      <VersionBar versions={g.versions} approved={g.approved_version}
        onView={setView} onSelect={setView} />
      {sb && (
        <>
          <button className="btn sm" style={{ marginBottom: 10 }} onClick={() => setShowCaption(!showCaption)}>
            {showCaption ? "收起" : "查看"} Music3 caption
          </button>
          {showCaption && (
            <pre style={{ whiteSpace: "pre-wrap", fontFamily: "var(--mono)", fontSize: 12,
              background: "var(--bg)", padding: 12, borderRadius: 8, color: "var(--muted)" }}>
              {sb.caption}
            </pre>
          )}
          <table className="shots">
            <thead><tr><th>#</th><th>类型</th><th>段落</th><th>歌词</th><th>秒</th><th>画面提示词</th></tr></thead>
            <tbody>
              {sb.shots.map((s) => (
                <tr key={s.id}>
                  <td>{s.id}</td>
                  <td><span className={`badge ${s.type}`}>{s.type === "singer" ? "歌手" : "分镜"}</span></td>
                  <td style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>{s.section}</td>
                  <td style={{ maxWidth: 160 }}>{s.lyric}</td>
                  <td style={{ fontFamily: "var(--mono)" }}>{s.duration}</td>
                  <td className="prompt">{s.prompt}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row">
            <div className="spacer" />
            <button className="btn" onClick={() => act(() => api.regenerate(proj.id, "storyboard"))}>↻ 重新生成</button>
            <button className="btn ok" disabled={isApproved}
              onClick={() => act(() => api.approve(proj.id, "storyboard", view ?? undefined))}>✓ 确认此版本</button>
          </div>
        </>
      )}
      {!sb && <div className="empty">确认歌词后自动生成分镜…</div>}
    </div>
  );
}

export function PortraitPanel({ proj, act }: { proj: Project; act: Act }) {
  const g = proj.gates.portrait;
  const v = g.versions.find((x) => x.id === g.approved_version) ?? g.versions.at(-1);
  const [pick, setPick] = useState<string | null>(null);
  const isApproved = g.approved_version != null;

  return (
    <div className="panel" id="gate-portrait">
      <h3>🧑‍🎤 歌手肖像 {isApproved && <span className="badge ok">已确认</span>}</h3>
      <p className="sub">点击选择要用作歌手形象的候选（确认后所有歌手镜头使用该形象）</p>
      {v?.images?.length ? (
        <>
          <div className="thumbs">
            {v.images.map((src, i) => (
              <button key={src} className={`thumb ${pick === src || (!pick && isApproved) ? "sel" : ""}`}
                onClick={() => setPick(src)}>
                <img src={src} alt={`候选 ${i + 1}`} />
                <span className="pick">{i + 1}</span>
              </button>
            ))}
          </div>
          <div className="row">
            <div className="spacer" />
            <button className="btn" onClick={() => act(() => api.regenerate(proj.id, "portrait"))}>↻ 换一批</button>
            <button className="btn ok" disabled={isApproved}
              onClick={() => act(() => api.approve(proj.id, "portrait"))}>✓ 确认肖像</button>
          </div>
        </>
      ) : <div className="empty">确认分镜后自动生成肖像候选…</div>}
    </div>
  );
}

export function AudioPanel({ proj, act }: { proj: Project; act: Act }) {
  const g = proj.gates.audio;
  const v = g.versions.find((x) => x.id === g.approved_version) ?? g.versions.at(-1);
  const isApproved = g.approved_version != null;

  return (
    <div className="panel" id="gate-audio">
      <h3>🎵 整曲 {isApproved && <span className="badge ok">已确认</span>}</h3>
      <p className="sub">MiniMax Music3 生成{v?.note ? ` · ${v.note}` : ""}</p>
      {v?.url ? (
        <>
          <audio className="wide" src={v.url} controls />
          <div className="row">
            <div className="spacer" />
            <button className="btn" onClick={() => act(() => api.regenerate(proj.id, "audio"))}>↻ 重唱一版</button>
            <button className="btn ok" disabled={isApproved}
              onClick={() => act(() => api.approve(proj.id, "audio"))}>✓ 确认整曲</button>
          </div>
        </>
      ) : <div className="empty">确认肖像后自动作曲…</div>}
    </div>
  );
}
