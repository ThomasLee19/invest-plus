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
import { Button, message, Tooltip } from 'antd'
import classNames from 'classnames'
import { TokenizerAndRendererExtension } from 'marked'
import { useMemo, useState } from 'react'
import styles from './result.module.scss'

// item.link 来自后端转发的网络搜索结果（Serper），不可信；只有 http/https
// 才允许打开，避免 javascript: 等伪协议造成 XSS/开放重定向。
function openExternal(link?: string) {
  if (!link) return
  try {
    const { protocol } = new URL(link)
    if (protocol !== 'http:' && protocol !== 'https:') return
  } catch {
    return
  }
  window.open(link, '_blank', 'noopener,noreferrer')
}

// 引用锚点 id 需要按消息隔离，否则多条带引用的回复会渲染出重复 DOM id，
// getElementById 只会命中文档中第一个，导致点击后定位到错误的消息。
function getSourceRefId(messageId: number, index: number) {
  return `source-ref-${messageId}-${index}`
}

// 后端一次性返回的 item.reference 是候选参考文档全集（最多 20 条），其中
// 未必每一条都真的被正文/思考过程用 ##N$$ 引用——直接展示全集会让来源列表
// 出现"看起来引用了但正文里根本没标注"的文档。这里按 think→content 的
// 阅读顺序扫描出实际出现过的引用编号（去重、忽略越界的幻觉编号），并把
// 它们重新映射为从 0 开始的连续序号，同时过滤出对应的文档，使来源列表与
// 正文引用一一对应、编号连续。
function buildReferenceOrder(item: API.ChatItem) {
  const reference = item.reference ?? []
  const text = `${item.think ?? ''}\n${item.content ?? ''}`
  const seen = new Set<number>()
  const orderedOldIndices: number[] = []
  const regex = /##(\d+)\$\$/g
  let match: RegExpExecArray | null
  while ((match = regex.exec(text))) {
    const oldIndex = Number(match[1])
    if (!seen.has(oldIndex) && reference[oldIndex]) {
      seen.add(oldIndex)
      orderedOldIndices.push(oldIndex)
    }
  }
  const indexMap = new Map<number, number>()
  orderedOldIndices.forEach((oldIndex, newIndex) => indexMap.set(oldIndex, newIndex))
  return {
    orderedReferences: orderedOldIndices.map((oldIndex) => reference[oldIndex]),
    indexMap,
  }
}

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

const Answer = (props: { item: API.ChatItem; indexMap: Map<number, number> }) => {
  const { item, indexMap } = props
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
              index,
              tokens: [],
            }
          }
        },
        renderer(token) {
          // token.index 是后端原始编号；重新映射为按正文引用顺序连续排列的
          // 新编号，与 Source 列表的过滤/重排保持一致。理论上 buildReferenceOrder
          // 已经用同样的正则扫描过同一段文本，映射必定存在；查不到时（不应发生）
          // 保守地不渲染角标，而不是显示一个未经过滤的原始编号造成不一致。
          const newIndex = indexMap.get(Number(token.index))
          if (newIndex == null) return ''
          return `<span class="reference-token" data-reference-index="${newIndex}">[${newIndex + 1}]</span>`
        },
      },
    ],
    [indexMap],
  )

  function handleReferenceClick(event: React.MouseEvent<HTMLDivElement>) {
    const target = (event.target as HTMLElement).closest?.('.reference-token')
    if (!target) return
    const index = target.getAttribute('data-reference-index')
    if (index == null) return

    const el = document.getElementById(getSourceRefId(item.id, Number(index)))
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

const Source = (props: { item: API.ChatItem; orderedReferences: API.Document[] }) => {
  const { item, orderedReferences } = props
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
        {orderedReferences.map((doc, index) => (
          <div
            key={index}
            id={getSourceRefId(item.id, index)}
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

const Images = (props: { item: API.ChatItem }) => {
  const { item } = props
  const { t } = useLang()

  return (
    <Section title={t.imageResultsTitle} icon={IconImage}>
      <div className={styles['chat-message-result__images']}>
        {item.image_results?.images?.map((item, index) => (
          <div
            className={styles.item}
            key={item.link || item.imageUrl || index}
            onClick={() => openExternal(item.link)}
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

const Videos = (props: { item: API.ChatItem }) => {
  const { item } = props
  const { t } = useLang()

  return (
    <Section title={t.videoResultsTitle} icon={IconVideo}>
      <div className={styles['chat-message-result__videos']}>
        {item.video_results?.videos?.map((item, index) => (
          <div
            className={styles.item}
            key={item.link || item.imageUrl || index}
            onClick={() => openExternal(item.link)}
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

const Related = (props: {
  item: API.ChatItem
  onSend?: (text: string) => void
}) => {
  const { item, onSend } = props
  const { t } = useLang()

  if (
    !item.recommended_questions?.length ||
    item.recommended_questions.filter((q) => q).length === 0
  )
    return null

  return (
    <Section title={t.relatedTitle} icon={IconRelated}>
      <div className={styles['chat-message-result__quick-reply']}>
        {item.recommended_questions?.map((item, index) => (
          <div
            className={styles['item']}
            key={`${index}-${item}`}
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

  const { orderedReferences, indexMap } = useMemo(
    () => buildReferenceOrder(item),
    [item.think, item.content, item.reference],
  )

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(item.content ?? '')
      message.success(t.copySuccess)
    } catch {
      message.error(t.copyFailed)
    }
  }

  function handleExport() {
    const url = `data:text/plain;charset=utf-8,${encodeURIComponent(item.content ?? '')}`
    const a = document.createElement('a')
    a.href = url
    a.download = 'output.txt'
    a.click()
  }

  return (
    <div className={styles['chat-message-result']}>
      {item.think || item.content || item.error ? (
        <Answer item={item} indexMap={indexMap} />
      ) : null}

      {item.loading ? null : (
        <div className={styles['chat-message-result__actions']}>
          <Tooltip title={t.actionCopy}>
            <Button variant="filled" color="default" shape="circle" onClick={handleCopy}>
              <img src={IconCopy} />
            </Button>
          </Tooltip>

          <Tooltip title={t.actionLike}>
            <Button
              variant="filled"
              color={liked === 'like' ? 'primary' : 'default'}
              shape="circle"
              onClick={() => setLiked(liked === 'like' ? null : 'like')}
            >
              <img src={IconLike} />
            </Button>
          </Tooltip>

          <Tooltip title={t.actionDislike}>
            <Button
              variant="filled"
              color={liked === 'dislike' ? 'danger' : 'default'}
              shape="circle"
              onClick={() => setLiked(liked === 'dislike' ? null : 'dislike')}
            >
              <img src={IconRemove} />
            </Button>
          </Tooltip>

          <Tooltip title={t.actionExport}>
            <Button variant="filled" color="default" shape="circle" onClick={handleExport}>
              <img src={IconShare} />
            </Button>
          </Tooltip>
        </div>
      )}

      {orderedReferences.length ? (
        <Source item={item} orderedReferences={orderedReferences} />
      ) : null}

      {item.image_results?.images?.length ? <Images item={item} /> : null}

      {item.video_results?.videos?.length ? <Videos item={item} /> : null}

      {!item.loading && isEnd && item.recommended_questions?.length ? (
        <Related item={item} onSend={onSend} />
      ) : null}
    </div>
  )
}
