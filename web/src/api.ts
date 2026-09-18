import type { AssStyle, Project } from "./types";

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const b = await r.json();
      detail = b.detail ?? JSON.stringify(b);
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export const api = {
  listProjects: () => fetch("/api/projects").then((r) => j<Project[]>(r)),
  getProject: (id: string) => fetch(`/api/projects/${id}`).then((r) => j<Project>(r)),
  createProject: (body: {
    theme?: string;
    lyrics_text?: string;
    title?: string;
    target_sec?: number;
    seed?: number | null;
    auto_approve?: boolean;
  }) =>
    fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => j<Project>(r)),
  approve: (id: string, gate: string, version?: number) =>
    fetch(`/api/projects/${id}/gates/${gate}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: version ?? null }),
    }).then((r) => j<Project>(r)),
  regenerate: (id: string, gate: string) =>
    fetch(`/api/projects/${id}/gates/${gate}/regenerate`, { method: "POST" }).then((r) =>
      j<Project>(r),
    ),
  editLyrics: (id: string, text: string) =>
    fetch(`/api/projects/${id}/gates/lyrics`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }).then((r) => j<Project>(r)),
  pickPortrait: (id: string, images: string[]) =>
    fetch(`/api/projects/${id}/gates/portrait`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ images }),
    }).then((r) => j<Project>(r)),
  putStyle: (id: string, style: AssStyle) =>
    fetch(`/api/projects/${id}/style`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ style }),
    }).then((r) => j<Project>(r)),
  compose: (id: string, style?: AssStyle | null) =>
    fetch(`/api/projects/${id}/compose`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ style: style ?? null }),
    }).then((r) => j<Project>(r)),
  assPreview: (id: string, style: AssStyle) =>
    fetch(`/api/projects/${id}/ass-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ style }),
    }).then((r) => j<{ image: string }>(r)),
};
