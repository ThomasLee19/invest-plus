import { createContext, useContext, useState } from 'react'

export type Lang = 'zh' | 'en'

export const messages = {
  zh: {
    tagline: 'Agent 自动调用 金融知识库（财报/新闻/科普）/ 实时行情 / 网络搜索，无需手动选择',
    bannerTitle: 'Invest+ 投研助手',
    bannerSubtitle: '你的 AI 金融投研助手，欢迎问我任何投资相关问题~',
    placeholder: '按 Enter 发送，Shift + Enter 换行',
    attachment: '附件（.txt / .md）',
    hotQuestions: [
      { emoji: '🍎', title: 'AAPL 最新的10-K报告披露了哪些风险因素？' },
      { emoji: '📈', title: 'MSFT 现在的股价和市盈率是多少？' },
      { emoji: '📰', title: 'GOOGL 最近有什么新闻？' },
      { emoji: '📊', title: '10-K 和 10-Q 有什么区别？' },
      { emoji: '🌐', title: '今天美股大盘走势如何？' },
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
    repoOfficialTitle: '官方示例语料',
    repoOfficialDesc: '内置的财报 / 新闻 / 科普语料库，只读，全部聊天会话均可检索。',
    repoUploadedTitle: '已上传文档',
    repoSessionTag: '会话',
    repoUploadModalTitle: '上传文件',
    repoUploadConfirm: '确认',
    repoUploadDragText: '拖拽文件到此处或',
    repoUploadDragTextHighlight: '点击上传',
    repoUploadDesc: '支持单个或批量上传文件，每个文件大小不超过5M，最多10个文件。',
    repoDeleteSuccess: '已删除',
    answerTitle: '答案',
    sourceTitle: '来源',
    actionCopy: '复制',
    actionLike: '点赞',
    actionDislike: '踩',
    actionExport: '导出为txt',
    uploadSuccess: '上传已完成',
    uploadFailed: '上传失败',
    fileTooLarge: '文件大小不能超过5M',
    copySuccess: '已复制',
    copyFailed: '复制失败',
    thinking: '深度探索中',
    failed: '失败',
    loading: '加载中...',
  },
  en: {
    tagline: 'Agent auto-calls Finance RAG (filings / news / education) / Live Market Data / Web Search — no manual selection needed',
    bannerTitle: 'Invest+ Research Assistant',
    bannerSubtitle: 'Your AI-powered equity research assistant. Ask me anything about the market!',
    placeholder: 'Press Enter to send, Shift + Enter for new line',
    attachment: 'Attachment (.txt / .md)',
    hotQuestions: [
      { emoji: '🍎', title: 'What risk factors did AAPL disclose in its latest 10-K?' },
      { emoji: '📈', title: "What's MSFT's current stock price and P/E ratio?" },
      { emoji: '📰', title: "What's the latest news on GOOGL?" },
      { emoji: '📊', title: "What's the difference between a 10-K and a 10-Q?" },
      { emoji: '🌐', title: 'How are U.S. markets trading today?' },
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
    repoOfficialTitle: 'Official Examples',
    repoOfficialDesc: 'Built-in filings / news / educational corpus, read-only and retrievable from every chat session.',
    repoUploadedTitle: 'Uploaded Documents',
    repoSessionTag: 'Session',
    repoUploadModalTitle: 'Upload File',
    repoUploadConfirm: 'Confirm',
    repoUploadDragText: 'Drag file here or',
    repoUploadDragTextHighlight: 'click to upload',
    repoUploadDesc: 'Supports single or bulk file upload. Files must not exceed 5M each, with a maximum of 10 files.',
    repoDeleteSuccess: 'Deleted',
    answerTitle: 'Answer',
    sourceTitle: 'Source',
    actionCopy: 'Copy',
    actionLike: 'Like',
    actionDislike: 'Dislike',
    actionExport: 'Export as txt',
    uploadSuccess: 'Upload complete',
    uploadFailed: 'Upload failed',
    fileTooLarge: 'File size must not exceed 5MB',
    copySuccess: 'Copied',
    copyFailed: 'Copy failed',
    thinking: 'Thinking...',
    failed: 'Failed',
    loading: 'Loading...',
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
