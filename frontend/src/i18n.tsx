import { createContext, useContext, useState } from 'react'

export type Lang = 'zh' | 'en'

export const messages = {
  zh: {
    tagline: 'Agent 自动调用 Smogon 攻略库 / PokeAPI / 网络搜索，无需手动选择',
    bannerTitle: 'PokemonRA 对战顾问',
    bannerSubtitle: '第九世代宝可梦对战策略助手，问我任何对战问题~',
    placeholder: '按 Enter 发送，Shift + Enter 换行',
    attachment: '附件（.txt / .md）',
    hotQuestions: [
      { emoji: '⚔️', title: '烈咬陆鲨适合什么对战策略？' },
      { emoji: '🐉', title: '幽尾玄鱼的速度种族值是多少？' },
      { emoji: '🏆', title: '朱紫赛季 meta 最强精灵有哪些？' },
      { emoji: '🛡️', title: '铁荆棘适合带什么道具和招式？' },
      { emoji: '🔥', title: '火属性对抗草/毒属性的克制倍率是多少？' },
    ],
    navNewChat: '新对话',
    navDocs: '文档',
    repoTitle: '数据集',
    repoDesc: '请等待文件解析完成后，再开始AI驱动的聊天。',
    repoAddFile: '添加文件',
    repoColName: '名称',
    repoColUpdated: '更新时间',
    repoColMethod: '分块方法',
    repoColStatus: '状态',
    repoColAction: '操作',
    answerTitle: '答案',
    uploadSuccess: '上传已完成',
    uploadFailed: '上传失败',
    fileTooLarge: '文件大小不能超过5M',
    copySuccess: '已复制',
    copyFailed: '复制失败',
    thinking: '深度探索中',
    failed: '失败',
  },
  en: {
    tagline: 'Agent auto-calls Smogon DB / PokeAPI / Web Search — no manual selection needed',
    bannerTitle: 'PokemonRA Battle Advisor',
    bannerSubtitle: 'Gen 9 Pokémon competitive strategy assistant. Ask me anything!',
    placeholder: 'Press Enter to send, Shift + Enter for new line',
    attachment: 'Attachment (.txt / .md)',
    hotQuestions: [
      { emoji: '⚔️', title: 'What are the best strategies for Garchomp?' },
      { emoji: '🐉', title: "What is Dragapult's speed stat?" },
      { emoji: '🏆', title: 'What are the top meta Pokémon in SV?' },
      { emoji: '🛡️', title: 'What items and moves work best on Iron Valiant?' },
      { emoji: '🔥', title: 'What is the fire vs grass/poison type matchup?' },
    ],
    navNewChat: 'New Chat',
    navDocs: 'Docs',
    repoTitle: 'Dataset',
    repoDesc: 'Please wait for file parsing to complete before starting AI-driven chat.',
    repoAddFile: 'Add File',
    repoColName: 'Name',
    repoColUpdated: 'Updated',
    repoColMethod: 'Chunk Method',
    repoColStatus: 'Status',
    repoColAction: 'Action',
    answerTitle: 'Answer',
    uploadSuccess: 'Upload complete',
    uploadFailed: 'Upload failed',
    fileTooLarge: 'File size must not exceed 5MB',
    copySuccess: 'Copied',
    copyFailed: 'Copy failed',
    thinking: 'Thinking...',
    failed: 'Failed',
  },
}

const LangContext = createContext<{
  lang: Lang
  setLang: (l: Lang) => void
}>({ lang: 'zh', setLang: () => {} })

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLang] = useState<Lang>('en')
  return <LangContext.Provider value={{ lang, setLang }}>{children}</LangContext.Provider>
}

export function useLang() {
  const { lang, setLang } = useContext(LangContext)
  return { lang, t: messages[lang], setLang }
}
