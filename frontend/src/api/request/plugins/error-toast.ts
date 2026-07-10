import { getMessages } from '@/i18n'
import { AxiosRequestConfig, AxiosResponse, CanceledError } from 'axios'
import { ResponseError } from '../error'
import { IRequestPlugin } from './plugin'

type Messages = ReturnType<typeof getMessages>
// 只允许指向字符串类型的 i18n key——原先用 keyof Messages 会放行 hotQuestions
// 这类数组字段，被下面对 response?.data?.* 的 any 兜底掩盖，未触发类型报错。
type StringMessageKey = { [K in keyof Messages]: Messages[K] extends string ? K : never }[keyof Messages]

const NETWORK_ERROR_STATUS_CODES: Record<number, StringMessageKey> = {
  429: 'tooManyRequests',
}

export const errorToastPlugin: IRequestPlugin = {
  postinstall(instance) {
    instance.interceptors.response.use(
      (response) => response,
      (error) => {
        const response = error.response as AxiosResponse<unknown> | undefined
        const config = (response?.config ?? error?.config) as AxiosRequestConfig

        if (config && !config.errorToast) return Promise.reject(error)

        // CanceledError 主要来源于 repeat.ts 取消重复请求
        // 该错误不应展示给用户
        if (error instanceof CanceledError) return Promise.reject(error)

        const status = response?.status
        const messages = getMessages()
        const statusKey = status != null ? NETWORK_ERROR_STATUS_CODES[status] : undefined
        // 展示用文案一律走 i18n，绝不信任 error.message——ResponseError 的
        // message 携带的是后端原始字符串（见 service.ts 构造时用的
        // data[MESSAGE_KEY]/detail），未经翻译且可能暴露实现细节，与
        // chat/index.tsx 里用 t.genericError 替换原始后端错误的做法一致。
        // 原始文案仅在此保留到控制台供排查。
        if (error instanceof ResponseError && error.rawMessage) {
          console.error('[request error]', error.rawMessage)
        }
        const message = (statusKey && messages[statusKey]) || messages.requestError

        window.$app.message.error(message)

        return Promise.reject(error)
      },
    )
  },
}
