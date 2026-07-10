import { AxiosRequestConfig } from 'axios'
import { request } from './request'

export function list(params?: Record<string, unknown>, options?: AxiosRequestConfig) {
  return request.get<API.Repository[]>('/get_files/', {
    ...options,
    params,
  })
}

export function listOfficialExamples(params?: Record<string, unknown>, options?: AxiosRequestConfig) {
  return request.get<API.OfficialExample[]>('/get_official_examples/', {
    ...options,
    params,
  })
}

export function deleteFile(
  params?: Pick<API.Repository, 'file_name' | 'session_id'>,
  options?: AxiosRequestConfig,
) {
  return request.delete<{ message: string }>('/delete_file/', {
    ...options,
    params,
  })
}
