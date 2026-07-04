import { createRequest } from './request'

// 当前后端是无鉴权的单用户模式（硬编码 USER_ID、不依赖 cookie/session），
// 因此状态变更请求没有 CSRF token 层。若将来改为基于 cookie 的会话鉴权，
// 需要在这里补上 CSRF token 机制（例如从 meta/接口获取 token 并注入请求头）。
export const request = createRequest({
  baseURL: import.meta.env.VITE_API_BASE,
  loading: true,
  errorToast: true,
  cancelRepeat: true,
})
