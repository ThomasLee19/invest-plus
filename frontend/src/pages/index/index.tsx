import * as api from '@/api'
import HomeBanner from '@/components/home-banner'
import HotQuestions from '@/components/hot-questions'
import ComSender from '@/components/sender'
import { transportToChatEnter } from '@/pages/chat/shared'
import { setPageTransport } from '@/utils'
import { useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import styles from './index.module.scss'

export default function Index() {
  const navigate = useNavigate()
  // 会话必须在首个附件上传之前就存在，否则上传会带着 session_id: undefined
  // 发出，之后创建的会话再也关联不到它。因此在首次上传/发送时懒创建一个会话，
  // 并缓存其 id，让上传和跳转复用同一个会话。
  // 缓存的是 Promise 本身而非已解析的 id：多个文件几乎同时触发上传时
  // （antd 对每个文件单独调用一次 beforeUpload），都会在第一个
  // session.create() 完成前读到 sessionIdRef.current 为空，若只缓存
  // 解析后的值会导致并发调用各自创建一个会话，附件被分散到不同会话。
  const sessionPromiseRef = useRef<Promise<string | undefined>>()

  const ensureSessionId = useCallback(() => {
    if (!sessionPromiseRef.current) {
      sessionPromiseRef.current = api.session
        .create()
        .then((res) => res.data.session_id)
    }
    return sessionPromiseRef.current
  }, [])

  const send = useCallback(
    async (message: string, files: string[]) => {
      const session_id = await ensureSessionId()
      setPageTransport(transportToChatEnter, {
        data: { message, attachments: files },
      })
      navigate(`/chat/${session_id}`)
    },
    [ensureSessionId, navigate],
  )

  return (
    <div className={styles.container}>
      <HomeBanner />
      <ComSender
        className={styles.sender}
        onSend={send}
        ensureSessionId={ensureSessionId}
      />
      <HotQuestions />
    </div>
  )
}
