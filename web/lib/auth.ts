"use client";
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { User } from "./types";

interface AuthState {
  user: User | null;
  hasHydrated: boolean;
  setUser: (user: User | null) => void;
  setHasHydrated: (hasHydrated: boolean) => void;
  logout: () => void;
}

const noopStorage: Storage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
  clear: () => {},
  key: () => null,
  length: 0,
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      hasHydrated: false,
      setUser: (user) => set({ user }),
      setHasHydrated: (hasHydrated) => set({ hasHydrated }),
      logout: () => set({ user: null }),
    }),
    {
      name: "piloci-auth",
      partialize: (state) => ({ user: state.user }),
      storage: createJSONStorage(() => {
        if (typeof window === "undefined") {
          return noopStorage;
        }

        try {
          return window.localStorage;
        } catch {
          return noopStorage;
        }
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    }
  )
);
