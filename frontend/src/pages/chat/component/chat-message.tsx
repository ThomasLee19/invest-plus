import { ChatRole } from '@/configs'
import { useLang } from '@/i18n'
import { SyncOutlined } from '@ant-design/icons'
import classNames from 'classnames'
import { useMemo } from 'react'
import styles from './chat-message.module.css'
import { Result } from './result'

// 用户消息组件，渲染用户发送的消息
function UserMessage(props: { item: API.ChatItem }) {
  const { item } = props

  return (
    <div
      className={classNames(
        styles['chat-message-item'],
        styles['chat-message-item--user'],
      )}
    >
      {item.content}
      {item.attachments?.length ? (
        <div className={styles['chat-message-item__attachments']}>
          {item.attachments.join(', ')}
        </div>
      ) : null}
    </div>
  )
}

function ResearchLoading(props: { status: 'processing' | 'success' }) {
  const { status } = props
  const { t } = useLang()
  if (status === 'success') return null

  return (
    <div className={styles['chat-status']}>
      {t.thinking}
      <SyncOutlined spin style={{ marginLeft: 8 }} />
    </div>
  )
}

// AI助手消息组件，渲染AI回复的消息
function AssistantMessage(props: {
  item: API.ChatItem
  isEnd?: boolean
  onSend?: (text: string) => void
}) {
  const { item, isEnd, onSend } = props

  return (
    <div className={classNames(styles['chat-message-item'])}>
      <Result item={item} isEnd={isEnd} onSend={onSend} />
    </div>
  )
}

// 聊天消息列表组件，根据消息类型渲染不同的消息组件
export default function ChatMessage(props: {
  list: API.ChatItem[]
  loading?: boolean
  deepResearch?: boolean
  onSend?: (text: string) => void
}) {
  const { list, onSend } = props

  const lastUserIndex = useMemo(() => {
    for (let i = list.length - 1; i >= 0; i--) {
      if (list[i].role === ChatRole.User) return i
    }
    return -1
  }, [list])

  return (
    <div className={styles['chat-message']}>
      {list.map((item, index) => {
        if (item.role === ChatRole.User) {
          const status: Parameters<typeof ResearchLoading>[0]['status'] =
            props.loading ? 'processing' : 'success'
          return (
            <div className={styles['user-message--wrapper']} key={item.id}>
              <UserMessage item={item} />
              {props.deepResearch && index === lastUserIndex && (
                <ResearchLoading status={status} />
              )}
            </div>
          )
        }

        return (
          <AssistantMessage
            key={item.id}
            item={item}
            isEnd={list.length - 1 === index}
            onSend={onSend}
          />
        )
      })}
    </div>
  )
}
