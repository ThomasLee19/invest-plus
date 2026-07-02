import { useLang } from '@/i18n'
import { Button } from 'antd'
import logo from '../../assets/logo.svg'
import styles from './index.module.scss'

export default function HeaderBar(props: { className?: string }) {
  const { lang, t, setLang } = useLang()

  return (
    <header className={`${styles['header-bar']} ${props.className || ''}`}>
      <img src={logo} alt="Logo" className={styles.logo} />
      <span>{import.meta.env.VITE_TITLE}</span>
      <span className={styles.tagline}>{t.tagline}</span>
      <div className={styles.langToggle}>
        <Button
          size="small"
          type={lang === 'en' ? 'primary' : 'default'}
          onClick={() => setLang('en')}
        >EN</Button>
        <Button
          size="small"
          type={lang === 'zh' ? 'primary' : 'default'}
          onClick={() => setLang('zh')}
        >中</Button>
      </div>
    </header>
  )
}
