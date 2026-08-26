import { create } from "zustand";

export type View =
  | { name: "dashboard" }
  | { name: "new-meeting" }
  | { name: "meeting" }
  | { name: "completion"; meetingId: string }
  | { name: "settings" }
  | { name: "templates" };

interface UIState {
  view: View;
  navigate: (view: View) => void;
}

export const useUIStore = create<UIState>((set) => ({
  view: { name: "dashboard" },
  navigate: (view) => set({ view }),
}));
