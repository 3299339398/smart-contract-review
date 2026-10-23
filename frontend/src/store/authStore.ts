import { create } from 'zustand'

interface User {
  id: number
  username: string
  role: string
}

interface AuthState {
  user: User | null
  isLoggedIn: boolean
  setUser: (user: User) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoggedIn: !!localStorage.getItem('accessToken'),
  setUser: (user) => set({ user, isLoggedIn: true }),
  logout: () => {
    localStorage.clear()
    set({ user: null, isLoggedIn: false })
  },
}))
