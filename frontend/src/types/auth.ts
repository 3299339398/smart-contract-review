export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  username: string
  email: string
  password: string
}

export interface LoginResponse {
  accessToken: string
  refreshToken: string
  expiresIn: number
  user: {
    id: number
    username: string
    role: string
  }
}

export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}
