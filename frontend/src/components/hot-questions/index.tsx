import { useLang } from '@/i18n'
import useSendMessage from '@/utils/useSendMessage'
import { useMemo } from 'react'
import { debounce } from 'throttle-debounce'
import styles from './index.module.scss'

interface HotQuestion {
  title: string
}

export default function HotQuestions() {
  const { t } = useLang()
  const list = t.hotQuestions

  const sendMessage = useSendMessage()
  // debounce 实例必须在多次渲染间保持同一个，否则每次重渲染都会重置计时器。
  const handleClick = useMemo(
    () =>
      debounce(300, async (question: HotQuestion) => {
        await sendMessage(question.title)
      }),
    [sendMessage],
  )

  return (
    <div className={styles.hotQuestions}>
      {list.map((question) => (
        <div
          key={question.title}
          className={styles.hotQuestion}
          onClick={() => handleClick(question)}
        >
          <span className={styles.title}>{question.title}</span>
        </div>
      ))}
    </div>
  )
}
