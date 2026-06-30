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

export function getSessions(options?: AxiosRequestConfig) {
  return request.get<{ session_id: string; session_name: string; created_at: string }[]>(
    '/sessions',
    options,
  )
}

export function deleteSession(
  params: { session_id: string },
  options?: AxiosRequestConfig,
) {
  return request.delete<{ message: string }>('/sessions', {
    ...options,
    params,
  })
}

export function upload(params: { files: File }, options?: AxiosRequestConfig) {
  const form = new FormData()
  form.append('files', params.files)
  return request.post<API.Result<{ file_id: string; url: string }>>(
    `/upload_files/`,
    form,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      ...options,
    },
  )
}
