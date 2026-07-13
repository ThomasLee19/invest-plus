import { createContext, useContext, useState } from 'react'

export type Lang = 'zh' | 'en'

export const messages = {
  zh: {
    tagline: 'Agent 自动调用 金融知识库（财报/新闻/科普）/ 实时行情 / 网络搜索，无需手动选择',
    bannerTitle: 'Invest+ 投研助手',
    bannerSubtitle: '你的 AI 金融投研助手，欢迎问我任何投资相关问题~',
    placeholder: '按 Enter 发送，Shift + Enter 换行',
    attachment: '附件（.txt / .md / .pdf）',
    hotQuestions: [
      { title: '苹果公司最新的10-K报告披露了哪些风险因素？' },
      { title: '微软公司现在的股价和市盈率是多少？' },
      { title: '谷歌公司最近有什么新闻？' },
      { title: '10-K 和 10-Q 有什么区别？' },
      { title: '今天美股大盘走势如何？' },
    ],
    navNewChat: '新对话',
    navDocs: '文档',
    repoTitle: '数据集',
    repoDesc: '请等待文件解析完成后，再开始AI驱动的聊天。',
    repoAddFile: '添加文件',
    repoColName: '名称',
    repoColUpdated: '更新时间 (UTC+8)',
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
    repoDeleteConfirmTitle: '确认删除该文件？',
    repoDeleteConfirmOk: '删除',
    repoDeleteConfirmCancel: '取消',
    answerTitle: '答案',
    sourceTitle: '来源',
    imageResultsTitle: '图像',
    videoResultsTitle: '视频',
    relatedTitle: '相关',
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
    genericError: '请求出错，请稍后重试。',
    apiDataError: '接口数据异常',
    tooManyRequests: '请求过于频繁，请稍后再试',
    requestError: '请求错误',
    statusUnparsed: '未解析',
    statusCancel: '已取消',
    statusSuccess: '已完成',
    statusFailed: '异常',
  },
  en: {
    tagline: 'Agent auto-calls Finance RAG (filings / news / education) / Live Market Data / Web Search — no manual selection needed',
    bannerTitle: 'Invest+ Research Assistant',
    bannerSubtitle: 'Your AI-powered equity research assistant. Ask me anything about the market!',
    placeholder: 'Press Enter to send, Shift + Enter for new line',
    attachment: 'Attachment (.txt / .md / .pdf)',
    hotQuestions: [
      { title: 'What risk factors did Apple disclose in its latest 10-K?' },
      { title: "What's Microsoft's current stock price and P/E ratio?" },
      { title: "What's the latest news on Google?" },
      { title: "What's the difference between a 10-K and a 10-Q?" },
      { title: 'How are U.S. markets trading today?' },
    ],
    navNewChat: 'New Chat',
    navDocs: 'Docs',
    repoTitle: 'Dataset',
    repoDesc: 'Please wait for file parsing to complete before starting AI-driven chat.',
    repoAddFile: 'Add File',
    repoColName: 'Name',
    repoColUpdated: 'Updated Time (UTC+8)',
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
    repoDeleteConfirmTitle: 'Delete this file?',
    repoDeleteConfirmOk: 'Delete',
    repoDeleteConfirmCancel: 'Cancel',
    answerTitle: 'Answer',
    sourceTitle: 'Source',
    imageResultsTitle: 'Images',
    videoResultsTitle: 'Videos',
    relatedTitle: 'Related',
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
    genericError: 'Something went wrong. Please try again.',
    apiDataError: 'Invalid API response',
    tooManyRequests: 'Too many requests, please try again later',
    requestError: 'Request error',
    statusUnparsed: 'Unparsed',
    statusCancel: 'Cancelled',
    statusSuccess: 'Completed',
    statusFailed: 'Failed',
  },
}

const LangContext = createContext<{
  lang: Lang
  setLang: (l: Lang) => void
}>({ lang: 'en', setLang: () => {} })

const LANG_STORAGE_KEY = 'lang'

// 初始语言：优先读 localStorage（用户上次的选择），否则回退到浏览器语言，
// 再回退到 'en'。这样刷新后不会把切换到中文的用户重置回英文。
function readStoredLang(): Lang {
  try {
    const stored = localStorage.getItem(LANG_STORAGE_KEY)
    if (stored === 'zh' || stored === 'en') return stored
  } catch {
    // localStorage 不可用（隐私模式等），忽略即可。
  }
  return navigator.language?.toLowerCase().startsWith('zh') ? 'zh' : 'en'
}

// 供非 React 模块（如 axios 拦截器插件）读取当前语言用——它们没有 hook
// 上下文可用，但仍需要把面向用户的字符串走 i18n 而不是硬编码中文。
// LangProvider 的 setLang 包一层同步更新它，保持与 React state 一致。
let currentLang: Lang = readStoredLang()

export function getMessages() {
  return messages[currentLang]
}

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => readStoredLang())
  const setLang = (l: Lang) => {
    currentLang = l
    try {
      localStorage.setItem(LANG_STORAGE_KEY, l)
    } catch {
      // localStorage 不可用时仅内存生效，不阻塞切换。
    }
    setLangState(l)
  }
  return <LangContext.Provider value={{ lang, setLang }}>{children}</LangContext.Provider>
}

export function useLang() {
  const { lang, setLang } = useContext(LangContext)
  return { lang, t: messages[lang], setLang }
}
