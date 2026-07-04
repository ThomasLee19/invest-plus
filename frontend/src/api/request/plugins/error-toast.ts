import { getMessages } from '@/i18n'
import { AxiosRequestConfig, AxiosResponse, CanceledError } from 'axios'
import { ResponseError } from '../error'
import { IRequestPlugin } from './plugin'

const NETWORK_ERROR_STATUS_CODES: Record<number, keyof ReturnType<typeof getMessages>> = {
  429: 'tooManyRequests',
}

export const errorToastPlugin: IRequestPlugin = {
  postinstall(instance) {
    instance.interceptors.response.use(
      (response) => response,
      (error) => {
        const response = error.response as AxiosResponse<any> | undefined
        const config = (response?.config ?? error?.config) as AxiosRequestConfig

        if (config && !config.errorToast) return Promise.reject(error)

        // CanceledError 主要来源于 repeat.ts 取消重复请求
        // 该错误不应展示给用户
        if (error instanceof CanceledError) return Promise.reject(error)

        const status = response?.status
        const messages = getMessages()
        const statusKey = status != null ? NETWORK_ERROR_STATUS_CODES[status] : undefined
        const message =
          error instanceof ResponseError
            ? error.message
            : (statusKey && messages[statusKey]) ||
              response?.data?.message ||
              response?.data?.detail ||
              response?.data?.error ||
              error.message ||
              messages.requestError

        window.$app.message.error(message)

        return Promise.reject(error)
      },
    )
  },
}
