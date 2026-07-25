/**
 * Invest+ 设计 token —— JS 侧镜像
 *
 * 同步修改：见 ./tokens.css（唯一真源）。键名 = CSS 变量名去掉 `--` 后的 camelCase，
 * 一一对应。两份文件由 `node scripts/check-tokens.mjs` 强制校验，改一处必须改另一处。
 *
 * ⚠️ 本文件内禁止出现 `var(` —— 全部值必须是字面量。
 *
 * 原因不是风格洁癖：`pages/repository/components/status.tsx` 会把这里的值直接喂给
 * `new Color(...)`，而 `new Color('var(--accent)')` 在渲染期 throw
 * （`Error: Unable to parse color from string: var(--accent)`）。该调用在 `useMemo`
 * 内、无 error boundary（`App.tsx` 的 `AntdApp` 不提供）→ /repository 整页白屏，
 * 而那正是三个验收页面之一。
 */

export const tokens = {
  // 画布与表面
  bgCanvas: '#fafaf9',
  bgSurface: '#ffffff',
  bgSubtle: '#f5f4f1',
  bgAccentSubtle: '#e6f2f2',

  // 边框
  borderDefault: '#e8e6e1',
  borderStrong: '#d6d3cc',

  // 文字
  textPrimary: '#1c1b1a',
  textSecondary: '#6b6862',
  textTertiary: '#75726c',
  textOnAccent: '#ffffff',

  // 强调色
  accent: '#0f6b6b',
  accentHover: '#0c5757',
  accentActive: '#094646',
  gradientBrand: 'linear-gradient(135deg, #0f6b6b 0%, #2e9e8f 100%)',
  overlayScrim:
    'linear-gradient( 180deg, rgba(28, 27, 26, 0.6) 0%, rgba(28, 27, 26, 0) 80% )',

  // 语义状态色（被 status.tsx 的 new Color() 消费，必须是合法色串）
  statusSuccess: '#2a7047',
  statusWarning: '#8f5100',
  statusDanger: '#b3261e',
  statusInfo: '#0f6b6b',
  statusNeutral: '#6b6862',

  // 字体
  fontSans:
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans SC', sans-serif",

  // 字阶
  fontXs: '12px',
  fontSm: '13px',
  fontBase: '14px',
  fontMd: '16px',
  fontLg: '20px',
  fontXl: '28px',
  fontXxl: '40px',

  lhXs: '1.5',
  lhSm: '1.55',
  lhBase: '1.65',
  lhMd: '1.6',
  lhLg: '1.4',
  lhXl: '1.3',
  lhXxl: '1.2',

  // 间距
  space1: '4px',
  space2: '8px',
  space3: '12px',
  space4: '16px',
  space5: '24px',
  space6: '32px',
  space7: '48px',
  space8: '64px',

  // 圆角
  radiusSm: '6px',
  radiusMd: '10px',
  radiusLg: '14px',
  radiusPill: '999px',

  // 阴影
  shadowXs: '0 1px 2px rgba(28, 27, 26, 0.04)',
  shadowSm: '0 2px 8px rgba(28, 27, 26, 0.06)',
  shadowMd: '0 8px 24px rgba(28, 27, 26, 0.08)',

  // 动效
  transitionBase: '150ms ease-out',
} as const

export type Tokens = typeof tokens
