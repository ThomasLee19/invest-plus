import * as api from '@/api'
import { transportToChatEnter } from '@/pages/chat/shared'
import { setPageTransport } from '@/utils'
import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'

export default function useSendMessage() {
  const navigate = useNavigate()

  return useCallback(
    async (message: string, attachments?: string[]) => {
      const { data } = await api.session.create()
      const session_id = data.session_id

      setPageTransport(transportToChatEnter, { data: { message, attachments } })
      navigate(`/chat/${session_id}`)
    },
    [navigate],
  )
}
