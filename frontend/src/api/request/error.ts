import { AxiosResponse } from 'axios'

export class ResponseError extends Error {
  response: AxiosResponse<any> | undefined
  // 后端原始错误文案，仅用于日志/排查，不可直接展示给用户——它未经 i18n，
  // 可能是英文或暴露后端实现细节（见 error-toast.ts 的处理）。
  rawMessage: string

  constructor(rawMessage: string, response?: AxiosResponse<any>) {
    super(rawMessage)
    this.name = 'ResponseError'
    this.rawMessage = rawMessage
    this.response = response
  }
}
