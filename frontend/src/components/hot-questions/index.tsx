import { useLang } from '@/i18n'
import useSendMessage from '@/utils/useSendMessage'
import { debounce } from 'throttle-debounce'
import styles from './index.module.scss'

interface HotQuestion {
  emoji: string
  title: string
}

interface HotQuestionsProps {
  list?: HotQuestion[]
}

export default function HotQuestions(props: HotQuestionsProps) {
  const { t } = useLang()
  const list = t.hotQuestions

  const sendMessage = useSendMessage()
  const handleClick = debounce(300, (question: HotQuestion) => {
    sendMessage(question.title)
  })

  return (
    <div className={styles.hotQuestions}>
      {list.map((question) => (
        <div
          key={question.title}
          className={styles.hotQuestion}
          onClick={() => handleClick(question)}
        >
          <span className={styles.emoji}>{question.emoji}</span>
          <span className={styles.title}>{question.title}</span>
        </div>
      ))}
    </div>
  )
}
