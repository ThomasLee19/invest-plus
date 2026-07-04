import { Router } from '@/router'
import { LangProvider, useLang } from '@/i18n'
import { App as AntdApp, ConfigProvider, Spin } from 'antd'
import enUS from 'antd/es/locale/en_US'
import zhCN from 'antd/es/locale/zh_CN'
import { useCallback, useEffect, useRef, useState } from 'react'
function App() {
  return (
    <LangProvider>
      <AppContent />
    </LangProvider>
  )
}

function AppContent() {
  const { lang } = useLang()
  return (
    <ConfigProvider
      locale={lang === 'zh' ? zhCN : enUS}
      theme={{
        cssVar: true,
        token: {
          colorPrimary: '#E3350D',
          fontSize: 14,
        },
      }}
    >
      <AntdApp>
        <Router />
        <MountApi />
      </AntdApp>
    </ConfigProvider>
  )
}

function MountApi() {
  const app = AntdApp.useApp()
  useEffect(() => {
    window.$app = app
  }, [app])
  const { t } = useLang()

  const [loading, setLoading] = useState(false)
  const [loadingText, setLoadingText] = useState('')
  const loadingCount = useRef(0)
  const showLoading = useCallback(({ title }: { title?: string } = {}) => {
    loadingCount.current++
    setLoading(true)
    setLoadingText(title ?? '')
  }, [])
  const hideLoading = useCallback(() => {
    loadingCount.current--
    setTimeout(() => {
      if (loadingCount.current <= 0) {
        setLoading(false)
        setLoadingText('')
      }
    }, 100)
  }, [])
  useEffect(() => {
    window.$showLoading = showLoading
    window.$hideLoading = hideLoading
  }, [showLoading, hideLoading])

  return (
    <>
      <Spin
        spinning={loading}
        tip={loadingText || t.loading}
        fullscreen
        style={{
          zIndex: 9999999,
        }}
      ></Spin>
    </>
  )
}

export default App
