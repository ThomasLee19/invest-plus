import * as api from '@/api'
import { transportToChatEnter } from '@/pages/chat/shared'
import { setPageTransport } from '@/utils'
import { useNavigate } from 'react-router-dom'

export default function useSendMessage() {
  const navigate = useNavigate()

  return async (message: string) => {
    const { data } = await api.session.create()
    const session_id = data.session_id

    setPageTransport(transportToChatEnter, { data: { message } })
    navigate(`/chat/${session_id}`)
  }
}
