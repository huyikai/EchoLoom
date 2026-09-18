export type GateName = "lyrics" | "storyboard" | "portrait" | "audio";

export interface VersionView {
  id: number;
  note: string;
  created_at: string;
  text?: string;
  storyboard?: Storyboard;
  images?: string[];
  url?: string;
  name?: string;
}

export interface GateView {
  versions: VersionView[];
  approved_version: number | null;
}

export interface Shot {
  id: number;
  type: "singer" | "scene";
  section: string;
  lyric: string;
  prompt: string;
  duration: number;
  transition: string;
}

export interface Storyboard {
  singer_desc: string;
  caption: string;
  shots: Shot[];
}

export interface AssStyle {
  font_name: string;
  font_size: number;
  bold: boolean;
  primary: string;
  secondary: string;
  outline_color: string;
  outline: number;
  shadow: number;
  alignment: number;
  margin_l: number;
  margin_r: number;
  margin_v: number;
  mode: "char" | "line";
  fade_ms: number;
}

export interface Project {
  id: string;
  title: string;
  theme: string;
  status: "draft" | "gathering" | "composing" | "done" | "failed";
  target_sec: number;
  seed: number;
  auto_approve: boolean;
  language: string;
  gates: Record<GateName, GateView>;
  ass_style: AssStyle;
  final: string | null;
  master: string | null;
  error: string;
  created_at: string;
}

export interface ProgressEvent {
  stage: string;
  msg: string;
  pct: number;
  ts?: string;
}
