import * as api from '@/api'
import ComPageLayout from '@/components/page-layout'
import ComSender from '@/components/sender'
import { ChatRole, ChatType } from '@/configs'
import { useLang } from '@/i18n'
import { deviceActions } from '@/store/device'
import { sessionState } from '@/store/session'
import { usePageTransport } from '@/utils'
import { useMount, useRequest, useUnmount } from 'ahooks'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { proxy, useSnapshot } from 'valtio'
import ChatMessage from './component/chat-message'
import styles from './index.module.scss'
import { createChatId, transportToChatEnter } from './shared'

// 滚动到页面底部的辅助函数，当距离底部小于阈值时自动滚动
// 多次调用会被折叠进同一帧，避免每个流式 token 都触发一次布局重排
let scrollFramePending = false
function scrollToBottom() {
  if (scrollFramePending) return
  scrollFramePending = true

  requestAnimationFrame(() => {
    scrollFramePending = false

    const threshold = 200
    const distanceToBottom =
      document.documentElement.scrollHeight -
      document.documentElement.scrollTop -
      document.documentElement.clientHeight

    if (distanceToBottom <= threshold) {
      window.scrollTo({
        top: document.documentElement.scrollHeight,
        behavior: 'smooth',
      })
    }
  })
}

export default function Index() {
  const { id } = useParams()
  const { data: ctx } = usePageTransport(transportToChatEnter)
  const sessionStore = useSnapshot(sessionState)
  const { t } = useLang()

  // 使用valtio管理聊天消息列表状态
  const [chat] = useState(() => {
    return proxy({
      list: [] as API.ChatItem[],
    })
  })
  const { list } = useSnapshot(chat) as { list: API.ChatItem[] }

  // 加载聊天历史记录
  const history = useRequest(
    async () => {
      const { data } = await api.session.detail({
        session_id: id!,
      })
      return data
    },
    {
      manual: true,
      onSuccess(data) {
        data.forEach((item) => {
          if (item.user_question) {
            chat.list.push({
              id: createChatId(),
              role: ChatRole.User,
              type: ChatType.Text,
              content: item.user_question,
            })
          }

          if (item.model_answer) {
            chat.list.push({
              id: createChatId(),
              role: ChatRole.Assistant,
              type: ChatType.Document,
              content: item.model_answer,
              think: item.think,
            })
          }
        })

        setTimeout(() => {
          window.scrollTo({
            top: document.documentElement.scrollHeight,
          })
        })
      },
    },
  )

  const loading = useMemo(() => {
    return list.some((o) => o.loading) || history.loading
  }, [list, history.loading])
  const loadingRef = useRef(loading)
  loadingRef.current = loading
  useEffect(() => {
    deviceActions.setChatting(loading)
  }, [loading])
  useUnmount(() => {
    deviceActions.setChatting(false)
  })

  // 发送聊天消息并处理流式响应
  const sendChat = useCallback(
    // 上传的附件已经在调用方通过 session 范围的 RAG 检索关联到本次会话
    // （见 backend rag_search 的 session_id scoping），不需要作为独立字段
    // 发到 /chat；attachments 只用于调用方把它显示在用户消息气泡里
    // （见下方 chat.list.push 里的 target.attachments）。
    async (target: API.ChatItem, message: string) => {
      target.loading = true
      try {
        const res = await api.session.chat({
          id: id!,
          message,
        })

        // 获取流式响应的reader
        const reader = res.data.getReader()
        if (!reader) return

        await read(reader)
      } catch (error: unknown) {
        // 展示给用户的是通用提示，而非后端原始错误字符串（可能是英文、未翻译，
        // 或暴露实现细节）；原始错误仍然通过 throw 保留给上层/控制台排查。
        target.error = t.genericError
        throw error
      } finally {
        target.loading = false
      }

      // 读取流式响应数据
      async function read(
        reader: ReadableStreamDefaultReader<AllowSharedBufferSource>,
      ) {
        let temp = ''
        const decoder = new TextDecoder('utf-8')
        while (true) {
          const { value, done } = await reader.read()
          temp += decoder.decode(value, { stream: true })

          // 按行解析SSE数据
          while (true) {
            const index = temp.indexOf('\n')
            if (index === -1) break

            const slice = temp.slice(0, index)
            temp = temp.slice(index + 1)

            if (slice.startsWith('data: ')) {
              parseData(slice)
              scrollToBottom()
            }
          }

          if (done) {
            temp += decoder.decode()
            target.loading = false
            break
          }
        }
      }

      // 解析SSE数据并更新聊天消息
      function parseData(slice: string) {
        try {
          const str = slice
            .trim()
            .replace(/^data: /, '')
            .trim()
          if (str === '[DONE]') {
            return
          }

          const json = JSON.parse(str)
          // agent 工具调用过程
          if (json?.role === 'agent' && json?.content) {
            target.think = `${target.think || ''}**[Agent]** ${json.content}\n\n`
            return
          }
          // 处理内容更新，区分思考内容和回答内容
          if (json?.content) {
            if (json.thinking) {
              target.think = `${target.think || ''}${json.content || ''}`
            } else {
              target.content = `${target.content || ''}${json.content || ''}`
            }
          }

          // 处理参考文档
          if (json?.documents?.length) {
            target.reference = json.documents
          }

          // 处理推荐问题
          if (json?.recommended_questions?.length) {
            target.recommended_questions = json.recommended_questions
          }

          // 处理图片结果
          if (json?.image_results) {
            target.image_results = json.image_results
          }

          // 处理视频结果
          if (json?.video_results) {
            target.video_results = json.video_results
          }
        } catch {
          // 单行 SSE 数据解析失败：跳过这一行即可，不影响后续行的处理。
        }
      }
    },
    [chat],
  )

  // 发送消息的主函数，处理用户输入并创建对话项
  const send = useCallback(
    async (message: string, attachments?: string[]) => {
      if (loadingRef.current) return
      if (!message) return

      if (chat.list.length === 0) {
        // 首次发送消息，创建用户消息和AI回复占位
        chat.list.push({
          id: createChatId(),
          role: ChatRole.User,
          type: ChatType.Text,
          content: message,
          attachments,
        })

        chat.list.push({
          id: createChatId(),
          role: ChatRole.Assistant,
          type: ChatType.Document,
          documents: [],
        })

        const target = chat.list[chat.list.length - 1]

        await sendChat(target, message!)
      } else {
        // 非首次发送，添加新的对话项
        chat.list.push({
          id: createChatId(),
          role: ChatRole.User,
          type: ChatType.Text,
          content: message,
          attachments,
        })

        chat.list.push({
          id: createChatId(),
          role: ChatRole.Assistant,
          type: ChatType.Document,
          content: '',
        })
        scrollToBottom()

        const target = chat.list[chat.list.length - 1]

        await sendChat(target, message!)
      }
    },
    [chat, sendChat],
  )
  // 组件挂载时，处理页面间传递的消息或加载历史记录
  useMount(async () => {
    if (ctx?.data.message) {
      send(ctx.data.message)
    } else {
      history.run()
    }
  })

  return (
    <ComPageLayout sender={<ComSender loading={loading} sessionId={id} onSend={send} />}>
      <div className={styles['chat-page']}>
        <ChatMessage
          list={list}
          loading={loading}
          deepResearch={sessionStore.useDeep}
          onSend={send}
        />
      </div>
    </ComPageLayout>
  )
}
