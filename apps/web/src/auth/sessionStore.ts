import { create } from "zustand";
import type { Session } from "@/api/types";

type SessionState = { session: Session | null; setSession: (session: Session) => void };
export const useSessionStore = create<SessionState>((set) => ({ session: null, setSession: (session) => set({ session }) }));
