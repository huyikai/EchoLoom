import { useEffect, useState } from "react";
import { api } from "./api";
import type { AssStyle, Project } from "./types";

type Act = (fn: () => Promise<Project>) => void;

const PRESETS: Record<string, Partial<AssStyle>> = {
  暗夜霓虹: { primary: "#00E5FF", secondary: "#F2F2F2", outline_color: "#101018", outline: 2, shadow: 1 },
  极简白: { primary: "#FFFFFF", secondary: "#9AA0A6", outline_color: "#000000", outline: 2, shadow: 0 },
  综艺描边: { primary: "#FFD54A", secondary: "#FFFFFF", outline_color: "#331100", outline: 3, shadow: 2 },
};

export function StyleEditor({ proj, act }: { proj: Project; act: Act }) {
  const [st, setSt] = useState<AssStyle>(proj.ass_style);
  const [preview, setPreview] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => { setSt(proj.ass_style); setDirty(false); }, [proj.id]); // eslint-disable-line

  const render = async (s: AssStyle) => {
    setBusy(true);
    try {
      const r = await api.assPreview(proj.id, s);
      setPreview(r.image);
    } catch { /* 项目尚无图片时后端会兜底渐变 */ }
    setBusy(false);
  };

  useEffect(() => { render(proj.ass_style); }, [proj.id]); // eslint-disable-line

  const set = (patch: Partial<AssStyle>) => {
    const next = { ...st, ...patch };
    setSt(next); setDirty(true);
    render(next);
  };

  return (
    <div className="panel">
      <h3>🅰 字幕样式</h3>
      <p className="sub">karaoke 逐字高亮 · 实时预览（合成时烧录进画面）</p>
      <div className="presets">
        {Object.entries(PRESETS).map(([name, p]) => (
          <button key={name} className="btn sm" onClick={() => set(p)}>{name}</button>
        ))}
      </div>
      <div className="stylegrid">
        <label className="fld">字号
          <input className="inp" type="number" min={20} max={120} value={st.font_size}
            onChange={(e) => set({ font_size: +e.target.value })} />
        </label>
        <label className="fld">字体
          <select className="inp" value={st.font_name}
            onChange={(e) => set({ font_name: e.target.value })}>
            <option>Microsoft YaHei</option>
            <option>SimHei</option>
            <option>KaiTi</option>
            <option>SimSun</option>
          </select>
        </label>
        <label className="fld">已唱高亮色
          <span className="colorrow">
            <input type="color" value={st.primary} onChange={(e) => set({ primary: e.target.value })} />
            <code style={{ fontSize: 11, color: "var(--dim)" }}>{st.primary}</code>
          </span>
        </label>
        <label className="fld">未唱颜色
          <span className="colorrow">
            <input type="color" value={st.secondary} onChange={(e) => set({ secondary: e.target.value })} />
            <code style={{ fontSize: 11, color: "var(--dim)" }}>{st.secondary}</code>
          </span>
        </label>
        <label className="fld">描边
          <input className="inp" type="number" min={0} max={6} step={0.5} value={st.outline}
            onChange={(e) => set({ outline: +e.target.value })} />
        </label>
        <label className="fld">阴影
          <input className="inp" type="number" min={0} max={4} value={st.shadow}
            onChange={(e) => set({ shadow: +e.target.value })} />
        </label>
        <label className="fld">高亮模式
          <span className="seg">
            <button className={st.mode === "char" ? "sel" : ""} onClick={() => set({ mode: "char" })}>逐字</button>
            <button className={st.mode === "line" ? "sel" : ""} onClick={() => set({ mode: "line" })}>逐行</button>
          </span>
        </label>
        <label className="fld">底部边距
          <input className="inp" type="number" min={0} max={300} value={st.margin_v}
            onChange={(e) => set({ margin_v: +e.target.value })} />
        </label>
      </div>
      {preview && <img className="preview" src={preview} alt="字幕预览" />}
      <div className="row">
        <button className="btn primary" disabled={!dirty} onClick={() => act(() => api.putStyle(proj.id, st))}>
          保存样式
        </button>
        <span style={{ color: "var(--dim)", fontSize: 12 }}>
          {busy ? "渲染预览中…" : dirty ? "有未保存修改" : "已保存"}
        </span>
      </div>
    </div>
  );
}
