import { LangProvider, useLang } from '@/i18n'
import { Router } from '@/router'
import { tokens } from '@/styles/tokens'
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
        // 取值全部来自 src/styles/tokens.ts（tokens.css 的 JS 侧镜像）。
        // 两份文件由 scripts/check-tokens.mjs 强制校验一致。
        // fontSize / borderRadius 用裸数字：antd 的这两个 token 是 number 形状，
        // 放进 tokens.ts 会让 check-tokens 的键值配对失效。
        token: {
          colorPrimary: tokens.accent,
          colorBgBase: tokens.bgCanvas,
          colorBgContainer: tokens.bgSurface,
          colorBgLayout: tokens.bgCanvas,
          colorBgElevated: tokens.bgSurface,
          colorText: tokens.textPrimary,
          colorTextSecondary: tokens.textSecondary,
          colorTextTertiary: tokens.textTertiary,
          colorBorder: tokens.borderDefault,
          colorBorderSecondary: tokens.borderDefault,
          colorSuccess: tokens.statusSuccess,
          colorWarning: tokens.statusWarning,
          colorError: tokens.statusDanger,
          colorLink: tokens.accent,
          fontFamily: tokens.fontSans,
          boxShadow: tokens.shadowSm,
          boxShadowSecondary: tokens.shadowMd,
          borderRadius: 10,
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
