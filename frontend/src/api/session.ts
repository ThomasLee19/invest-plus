import { AxiosRequestConfig } from 'axios'
import { request } from './request'

export function detail(
  params: {
    session_id: string
  },
  options?: AxiosRequestConfig,
) {
  return request.get<
    {
      user_question: string
      model_answer: string
      think?: string
      created_at: string
    }[]
  >(`/messages`, {
    ...options,
    params,
  })
}

export function create(params?: {}, options?: AxiosRequestConfig) {
  return request.post<
    API.Result<{
      session_id: string
    }>
  >(`/create_session`, params, options)
}

export function chat(
  params: {
    id: string
    message: string
  },
  options?: AxiosRequestConfig,
) {
  const { id, ..._params } = params
  return request.post<ReadableStream>(
    '/chat',
    {
      ..._params,
    },
    {
      headers: {
        Accept: 'text/event-stream',
      },
      responseType: 'stream',
      adapter: 'fetch',
      loading: false,
      params: {
        session_id: id,
      },
      ...options,
    },
  )
}

export function upload(
  params: { files: File; session_id?: string },
  options?: AxiosRequestConfig,
) {
  const { files, session_id } = params
  const form = new FormData()
  form.append('files', files)
  return request.post<API.Result<{ file_id: string; url: string }>>(
    `/upload_files/`,
    form,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      params: session_id ? { session_id } : undefined,
      ...options,
    },
  )
}
