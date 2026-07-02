import IconAnswer from '@/assets/chat/answer.svg'
import IconCopy from '@/assets/chat/copy.svg'
import IconImage from '@/assets/chat/image.svg'
import IconLike from '@/assets/chat/like.svg'
import IconPlay from '@/assets/chat/play.svg'
import IconRelated from '@/assets/chat/related.svg'
import IconRemove from '@/assets/chat/remove.svg'
import IconShare from '@/assets/chat/share.svg'
import IconSource from '@/assets/chat/source.svg'
import IconVideo from '@/assets/chat/video.svg'
import Markdown from '@/components/markdown'
import { useLang } from '@/i18n'
import { PlusOutlined } from '@ant-design/icons'
import { Button, Dropdown, message } from 'antd'
import classNames from 'classnames'
import { TokenizerAndRendererExtension } from 'marked'
import { useMemo, useState } from 'react'
import styles from './result.module.scss'

const Section = (props: {
  title: string
  icon: string
  children: React.ReactNode
}) => {
  return (
    <div className={styles['chat-message-result-section']}>
      <div className={styles['chat-message-result-section__title']}>
        <img className={styles.icon} src={props.icon} />
        <span className={styles.title}>{props.title}</span>
      </div>
      {props.children}
    </div>
  )
}

const 答案 = (props: { item: API.ChatItem }) => {
  const { item } = props
  const { t } = useLang()

  /* markdown */
  const extensions = useMemo<TokenizerAndRendererExtension[]>(
    () => [
      {
        name: 'reference',
        level: 'inline',
        start(src) {
          return src.match(/##\d+\$\$/)?.index
        },
        tokenizer(src) {
          const match = /^##(\d+?)\$\$/.exec(src)
          if (match) {
            const [raw, index] = match
            return {
              type: 'reference',
              raw,
              index: this.lexer.inlineTokens(index),
              tokens: [],
            }
          }
        },
        renderer(token) {
          const index = this.parser.parseInline(token.index)
          return `<span class="refrence-token" data-refrence-index="${index}">[${Number(index) + 1}]</span>`
        },
      },
    ],
    [],
  )

  function handleReferenceClick(event: React.MouseEvent<HTMLDivElement>) {
    const target = (event.target as HTMLElement).closest?.('.refrence-token')
    if (!target) return
    const index = target.getAttribute('data-refrence-index')
    if (index == null) return

    const el = document.getElementById(`source-ref-${index}`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    if (el) {
      el.classList.add(styles['source-highlight'])
      setTimeout(() => el.classList.remove(styles['source-highlight']), 2500)
    }
  }

  return (
    <Section title={t.answerTitle} icon={IconAnswer}>
      <div onClick={handleReferenceClick}>
        {item.think ? (
          <Markdown
            className={classNames(
              styles['chat-message-result__think'],
              styles['chat-message-result__md'],
            )}
            value={item.think}
            extensions={extensions}
          />
        ) : null}

        {item.content ? (
          <Markdown
            className={styles['chat-message-result__md']}
            value={item.content}
            extensions={extensions}
          />
        ) : null}
      </div>

      {item.error ? (
        <div className={styles['chat-message-result__error']}>{item.error}</div>
      ) : null}
    </Section>
  )
}

const 来源 = (props: { item: API.ChatItem }) => {
  const { item } = props
  const { t } = useLang()
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  function toggleExpanded(index: number) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }

  return (
    <Section title={t.sourceTitle} icon={IconSource}>
      <div className={styles['chat-message-result__source']}>
        {item.reference?.map((doc, index) => (
          <div
            key={doc.document_id}
            id={`source-ref-${index}`}
            className={styles.item}
            onClick={() => toggleExpanded(index)}
          >
            <div className={styles.index}>[{index + 1}]</div>
            <div className={styles.title}>{doc.document_name}</div>
            <div
              className={classNames(styles.content, {
                [styles['content--expanded']]: expanded.has(index),
              })}
            >
              {doc.content_with_weight}
            </div>
          </div>
        ))}
      </div>
    </Section>
  )
}

const 笔记 = (props: { item: API.ChatItem }) => {
  const { item } = props
  console.log(item)

  // 后端暂未实现，使用假数据代替
  return (
    <Section title="笔记" icon={IconImage}>
      <div className={styles['chat-message-result__xhs']}>
        {Array.from({ length: 4 }).map((_) => (
          <div className={styles.item}>
            <div className={styles.header}>
              <img className={styles.cover} src={IconShare} />
            </div>

            <div className={styles.footer}>
              <div className={styles.title}>
                如何培养孩子的兴趣？家长学会这三点，孩子受益匪浅 - Classover
              </div>

              <div className={styles.user}>
                <img className={styles.avatar} src={IconShare} />
                <div className={styles.name}>Classover</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </Section>
  )
}

const 图像 = (props: { item: API.ChatItem }) => {
  const { item } = props

  return (
    <Section title="图像" icon={IconImage}>
      <div className={styles['chat-message-result__images']}>
        {item.image_results?.images?.map((item, index) => (
          <div
            className={styles.item}
            key={index}
            onClick={() => window.open(item.link, '_blank')}
          >
            <div className={styles.box}>
              <img className={styles.cover} src={item.thumbnailUrl} />
            </div>
          </div>
        ))}
      </div>
    </Section>
  )
}

const 视频 = (props: { item: API.ChatItem }) => {
  const { item } = props

  return (
    <Section title="视频" icon={IconVideo}>
      <div className={styles['chat-message-result__videos']}>
        {item.video_results?.videos?.map((item, index) => (
          <div
            className={styles.item}
            key={index}
            onClick={() => window.open(item.link, '_blank')}
          >
            <div className={styles.box}>
              <img className={styles.cover} src={item.imageUrl} />

              <img className={styles.play} src={IconPlay} />
            </div>
          </div>
        ))}
      </div>
    </Section>
  )
}

const 相关 = (props: {
  item: API.ChatItem
  onSend?: (text: string) => void
}) => {
  const { item, onSend } = props

  if (
    !item.recommended_questions?.length ||
    item.recommended_questions.filter((q) => q).length === 0
  )
    return null

  return (
    <Section title="相关" icon={IconRelated}>
      <div className={styles['chat-message-result__quick-reply']}>
        {item.recommended_questions?.map((item, index) => (
          <div
            className={styles['item']}
            key={index}
            onClick={() => onSend?.(item)}
          >
            <span className={styles['text']}>
              {index + 1}．{item}
            </span>
            <PlusOutlined className={styles['arrow']} />
          </div>
        ))}
      </div>
    </Section>
  )
}

export function Result(props: {
  item: API.ChatItem
  isEnd?: boolean
  onSend?: (text: string) => void
}) {
  const { item, isEnd, onSend } = props
  const [liked, setLiked] = useState<'like' | 'dislike' | null>(null)
  const { t } = useLang()

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(item.content ?? '')
      message.success(t.copySuccess)
    } catch {
      message.error(t.copyFailed)
    }
  }

  const shareMenu = useMemo(() => {
    return [
      {
        key: 'txt',
        label: 'Export as txt',
        onClick: async () => {
          const url = `data:text/plain;charset=utf-8,${encodeURIComponent(item.content ?? '')}`
          const a = document.createElement('a')
          a.href = url
          a.download = 'output.txt'
          a.click()
        },
      },
    ]
  }, [item.content])

  return (
    <div className={styles['chat-message-result']}>
      {item.think || item.content || item.error ? <答案 item={item} /> : null}

      {item.loading ? null : (
        <div className={styles['chat-message-result__actions']}>
          <Button variant="filled" color="default" shape="circle" onClick={handleCopy} title="复制">
            <img src={IconCopy} />
          </Button>

          <Button
            variant="filled"
            color={liked === 'like' ? 'primary' : 'default'}
            shape="circle"
            onClick={() => setLiked(liked === 'like' ? null : 'like')}
            title="点赞"
          >
            <img src={IconLike} />
          </Button>

          <Button
            variant="filled"
            color={liked === 'dislike' ? 'danger' : 'default'}
            shape="circle"
            onClick={() => setLiked(liked === 'dislike' ? null : 'dislike')}
            title="踩"
          >
            <img src={IconRemove} />
          </Button>

          <Dropdown menu={{ items: shareMenu }}>
            <Button variant="filled" color="default" shape="circle" title="导出">
              <img src={IconShare} />
            </Button>
          </Dropdown>
        </div>
      )}

      {item.reference?.length ? <来源 item={item} /> : null}

      {false ? <笔记 item={item} /> : null}

      {item.image_results?.images?.length ? <图像 item={item} /> : null}

      {item.video_results?.videos?.length ? <视频 item={item} /> : null}

      {!item.loading && isEnd && item.recommended_questions?.length ? (
        <相关 item={item} onSend={onSend} />
      ) : null}
    </div>
  )
}
