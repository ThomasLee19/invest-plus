import * as api from '@/api'
import { useLang } from '@/i18n'
import { transportToChatEnter } from '@/pages/chat/shared'
import { setPageTransport } from '@/utils'
import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'

export default function useSendMessage() {
  const navigate = useNavigate()
  const { t } = useLang()

  return useCallback(
    async (message: string, attachments?: string[]) => {
      let session_id: string | undefined
      try {
        const { data } = await api.session.create()
        session_id = data.session_id
      } catch {
        window.$app.message.error(t.genericError)
        return
      }

      if (!session_id) {
        window.$app.message.error(t.genericError)
        return
      }

      setPageTransport(transportToChatEnter, { data: { message, attachments } })
      navigate(`/chat/${session_id}`)
    },
    [navigate, t],
  )
}
