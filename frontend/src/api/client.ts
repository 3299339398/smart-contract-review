import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

let refreshPromise: Promise<any> | null = null
let isRefreshingFailed = false

apiClient.interceptors.request.use((config) => {
  if (isRefreshingFailed) {
    return Promise.reject(new axios.Cancel('Token refresh failed, redirecting to login'))
  }
  const token = localStorage.getItem('accessToken')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true
      const refreshToken = localStorage.getItem('refreshToken')
      if (refreshToken && !isRefreshingFailed) {
        try {
          if (!refreshPromise) {
            refreshPromise = axios.post('/api/v1/auth/refresh', { refreshToken })
              .then(({ data }) => {
                localStorage.setItem('accessToken', data.data.accessToken)
                localStorage.setItem('refreshToken', data.data.refreshToken)
                return data.data.accessToken
              })
              .finally(() => { refreshPromise = null })
          }
          const newToken = await refreshPromise
          original.headers.Authorization = `Bearer ${newToken}`
          return apiClient(original)
        } catch {
          isRefreshingFailed = true
          localStorage.clear()
          window.location.replace('/login')
          return Promise.reject(error)
        }
      }
      // No refresh token or already failed — just redirect
      localStorage.clear()
      window.location.replace('/login')
      return Promise.reject(error)
    }
    return Promise.reject(error)
  }
)

export default apiClient
